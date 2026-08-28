import httpx
import pytest

from app.providers.base import ProviderAuthError, ProviderRateLimited
from app.providers.retry import MAX_DELAY_SECONDS, call_with_retry


def _response(status_code: int, headers: dict | None = None) -> httpx.Response:
    request = httpx.Request("POST", "https://api.example.com/x")
    return httpx.Response(status_code=status_code, headers=headers or {}, request=request)


def test_returns_response_immediately_on_success():
    calls = []

    def send():
        calls.append(1)
        return _response(200)

    response = call_with_retry(send)

    assert response.status_code == 200
    assert len(calls) == 1


def test_raises_provider_auth_error_immediately_on_401_no_retry():
    calls = []

    def send():
        calls.append(1)
        return _response(401)

    with pytest.raises(ProviderAuthError):
        call_with_retry(send)

    assert len(calls) == 1  # must not retry a bad key


def test_raises_provider_auth_error_immediately_on_403_no_retry():
    calls = []

    def send():
        calls.append(1)
        return _response(403)

    with pytest.raises(ProviderAuthError):
        call_with_retry(send)

    assert len(calls) == 1


def test_retries_429_then_succeeds(monkeypatch):
    monkeypatch.setattr("app.providers.retry.time.sleep", lambda *_: None)
    responses = [_response(429), _response(429), _response(200)]

    def send():
        return responses.pop(0)

    response = call_with_retry(send)

    assert response.status_code == 200
    assert responses == []


def test_raises_provider_rate_limited_after_exhausting_attempts(monkeypatch):
    monkeypatch.setattr("app.providers.retry.time.sleep", lambda *_: None)
    calls = []

    def send():
        calls.append(1)
        return _response(429, headers={"Retry-After": "12"})

    with pytest.raises(ProviderRateLimited) as exc_info:
        call_with_retry(send)

    assert exc_info.value.retry_after == 12.0
    assert len(calls) == 4  # exactly MAX_ATTEMPTS, no more, no fewer


def test_retries_5xx_then_succeeds(monkeypatch):
    monkeypatch.setattr("app.providers.retry.time.sleep", lambda *_: None)
    responses = [_response(503), _response(200)]

    def send():
        return responses.pop(0)

    response = call_with_retry(send)

    assert response.status_code == 200


def test_raises_http_status_error_on_permanent_4xx_without_retry():
    calls = []

    def send():
        calls.append(1)
        return _response(400)

    with pytest.raises(httpx.HTTPStatusError):
        call_with_retry(send)

    assert len(calls) == 1  # a plain bad request is not retried


def test_retries_transport_error_then_succeeds(monkeypatch):
    monkeypatch.setattr("app.providers.retry.time.sleep", lambda *_: None)
    attempts = {"n": 0}

    def send():
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise httpx.ConnectError("connection refused")
        return _response(200)

    response = call_with_retry(send)

    assert response.status_code == 200
    assert attempts["n"] == 2


def test_reraises_transport_error_after_exhausting_attempts(monkeypatch):
    monkeypatch.setattr("app.providers.retry.time.sleep", lambda *_: None)
    attempts = {"n": 0}

    def send():
        attempts["n"] += 1
        raise httpx.ConnectError("connection refused")

    with pytest.raises(httpx.ConnectError):
        call_with_retry(send)

    assert attempts["n"] == 4  # exactly MAX_ATTEMPTS, no more, no fewer


def test_retry_after_is_capped_at_max_delay_seconds(monkeypatch):
    slept_durations = []
    monkeypatch.setattr("app.providers.retry.time.sleep", lambda seconds: slept_durations.append(seconds))

    def send():
        return _response(429, headers={"Retry-After": "3600"})  # 1 hour, way over any sane cap

    with pytest.raises(ProviderRateLimited):
        call_with_retry(send)

    assert all(d <= MAX_DELAY_SECONDS for d in slept_durations)
    assert len(slept_durations) == 3  # 3 sleeps between 4 attempts
