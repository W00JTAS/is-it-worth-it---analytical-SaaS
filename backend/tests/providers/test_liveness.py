import httpx

from app.providers.liveness import is_confirmed_dead


class _FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


class _FakeClient:
    def __init__(self, status_code: int | None = None, raises: Exception | None = None):
        self._status_code = status_code
        self._raises = raises
        self.calls: list[dict] = []

    def head(self, url, timeout=None, follow_redirects=None):
        self.calls.append({"url": url, "timeout": timeout, "follow_redirects": follow_redirects})
        if self._raises is not None:
            raise self._raises
        return _FakeResponse(self._status_code)


def test_confirmed_dead_on_404():
    client = _FakeClient(status_code=404)
    assert is_confirmed_dead("https://example.com/gone", client) is True


def test_not_dead_on_200():
    client = _FakeClient(status_code=200)
    assert is_confirmed_dead("https://example.com/alive", client) is False


def test_not_dead_on_403_bot_block():
    # Allegro and other gated marketplaces 403 plain HTTP clients even for
    # genuinely live, correct offers — a 403 must never be treated as dead.
    client = _FakeClient(status_code=403)
    assert is_confirmed_dead("https://allegro.pl/produkt/x", client) is False


def test_not_dead_on_timeout():
    client = _FakeClient(raises=httpx.ReadTimeout("timed out"))
    assert is_confirmed_dead("https://example.com/slow", client) is False


def test_not_dead_on_connection_error():
    client = _FakeClient(raises=httpx.ConnectError("refused"))
    assert is_confirmed_dead("https://example.com/unreachable", client) is False


def test_uses_a_bounded_timeout_and_follows_redirects():
    client = _FakeClient(status_code=200)
    is_confirmed_dead("https://example.com/x", client)
    assert client.calls[0]["timeout"] == 5.0
    assert client.calls[0]["follow_redirects"] is True
