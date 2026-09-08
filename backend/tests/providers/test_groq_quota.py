import pytest

from scripts.groq_quota import ProbeResult, main, probe, verdict


class _FakeResponse:
    def __init__(self, payload: dict, headers: dict[str, str], status_code: int = 200):
        self._payload = payload
        self.headers = headers
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    """Mirrors test_groq.py's fake client pattern (a plain class with a
    `.post()` method returning a fake response), extended with `.headers`.
    """

    def __init__(self, response: _FakeResponse):
        self._response = response
        self.requests: list[dict] = []

    def post(self, url, headers, json):
        self.requests.append({"url": url, "headers": headers, "json": json})
        return self._response


_SUCCESS_HEADERS = {
    "x-ratelimit-limit-requests": "250",
    "x-ratelimit-limit-tokens": "70000",
    "x-ratelimit-remaining-requests": "249",
    "x-ratelimit-remaining-tokens": "69988",
    "x-ratelimit-reset-requests": "5h44m",
    "x-ratelimit-reset-tokens": "6ms",
    "content-type": "application/json",
}

_RATE_LIMIT_HEADERS = {
    "x-ratelimit-remaining-requests": "86",
    "x-ratelimit-remaining-tokens": "0",
    "content-type": "application/json",
}


def test_successful_probe_reports_ratelimit_headers_and_succeeds():
    client = _FakeClient(_FakeResponse({}, headers=_SUCCESS_HEADERS, status_code=200))

    result = probe(client, api_key="test-key")

    assert result.success is True
    assert result.status_code == 200
    # Only x-ratelimit-* headers are surfaced, not every response header.
    assert result.ratelimit_headers == {
        k: v for k, v in _SUCCESS_HEADERS.items() if k.startswith("x-ratelimit-")
    }
    assert "content-type" not in result.ratelimit_headers
    assert result.error_message is None

    assert client.requests[0]["headers"]["Authorization"] == "Bearer test-key"
    assert client.requests[0]["json"]["model"] == "groq/compound-mini"


def test_successful_probe_verdict_estimates_remaining_lookups():
    result = ProbeResult(
        success=True, status_code=200,
        ratelimit_headers={"x-ratelimit-remaining-tokens": "69988"},
    )

    line = verdict(result)

    assert line.startswith("OK")
    assert "34" in line  # 69988 // 2000
    # The number is compound-mini's OWN token counter, which does not reflect
    # the internal orchestration model's daily budget that actually binds,
    # so the verdict must not read as a prediction of how many lookups work.
    assert "upper bound only" in line
    assert "internal per-model daily" in line
    assert "estimated remaining today" not in line


def test_rate_limited_probe_extracts_error_message_and_does_not_raise():
    payload = {
        "error": {
            "message": (
                "Rate limit reached for model llama-3.3-70b-versatile ... on "
                "tokens per day (TPD): Limit 100000, Used 98623, Requested 3291"
            ),
        },
    }
    client = _FakeClient(_FakeResponse(payload, headers=_RATE_LIMIT_HEADERS, status_code=429))

    result = probe(client, api_key="test-key")

    assert result.success is False
    assert result.status_code == 429
    assert "llama-3.3-70b-versatile" in result.error_message
    assert result.ratelimit_headers == {
        k: v for k, v in _RATE_LIMIT_HEADERS.items() if k.startswith("x-ratelimit-")
    }


def test_rate_limited_probe_verdict_reports_exhausted():
    result = ProbeResult(success=False, status_code=429, error_message="Rate limit reached")

    assert verdict(result) == "EXHAUSTED - quota errored on the probe call itself"


def test_main_raises_systemexit_without_network_call_when_api_key_missing(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    class _ExplodingClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("main() must not construct an httpx.Client without an API key")

    monkeypatch.setattr("scripts.groq_quota.httpx.Client", _ExplodingClient)

    with pytest.raises(SystemExit) as exc_info:
        main(argv=[])

    assert "GROQ_API_KEY" in str(exc_info.value)


def test_main_exits_zero_on_successful_probe(monkeypatch, capsys):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    client = _FakeClient(_FakeResponse({}, headers=_SUCCESS_HEADERS, status_code=200))
    monkeypatch.setattr("scripts.groq_quota.httpx.Client", lambda timeout: client)

    with pytest.raises(SystemExit) as exc_info:
        main(argv=[])

    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "x-ratelimit-remaining-tokens: 69988" in out
    assert "lookups possible under this header's counter alone" in out
    assert "upper bound only" in out


def test_main_exits_one_on_rate_limited_probe(monkeypatch, capsys):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    payload = {"error": {"message": "Rate limit reached for model llama-3.3-70b-versatile"}}
    client = _FakeClient(_FakeResponse(payload, headers=_RATE_LIMIT_HEADERS, status_code=429))
    monkeypatch.setattr("scripts.groq_quota.httpx.Client", lambda timeout: client)

    with pytest.raises(SystemExit) as exc_info:
        main(argv=[])

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "error.message: Rate limit reached for model llama-3.3-70b-versatile" in out
    assert "EXHAUSTED" in out
