import json
from decimal import Decimal

import httpx
import pytest

from app.models.product import Product
from app.providers.base import ProviderAuthError, ProviderRateLimited, ProviderUnavailable
from app.providers.firecrawl import SEARCH_API_URL, FirecrawlProvider
from app.providers.groq import API_URL as GROQ_API_URL


def _make_product(**overrides) -> Product:
    defaults = dict(
        tenant_id="t1", source="csv", external_id="1", variant_id=None,
        name="Test Product", ean="5901234123457",
        wholesale_price=Decimal("60.00"), currency="PLN", category="Test",
    )
    defaults.update(overrides)
    return Product(**defaults)


def _search_response(web: list[dict] | None) -> dict:
    data = {"web": web} if web is not None else {}
    return {"success": True, "data": data, "creditsUsed": 2}


def _extract_response(parsed: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(parsed)}}]}


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200, headers: dict | None = None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


class _TwoServiceClient:
    """Returns `search_payload` for the Firecrawl search call, `extract_payload`
    for the Groq extraction call, distinguishing by URL — the two providers
    hit different hosts entirely."""

    def __init__(self, search_payload: dict, extract_payload: dict):
        self._search_payload = search_payload
        self._extract_payload = extract_payload
        self.requests: list[dict] = []

    def post(self, url, headers, json):
        self.requests.append({"url": url, "headers": headers, "json": json})
        if url == SEARCH_API_URL:
            return _FakeResponse(self._search_payload)
        return _FakeResponse(self._extract_payload)


def test_two_call_flow_returns_offer_with_citations_from_search_results():
    client = _TwoServiceClient(
        search_payload=_search_response([
            {"title": "Example Shop", "description": "Cena: 89.99 zl", "url": "https://example.com/product", "position": 1},
        ]),
        extract_payload=_extract_response({
            "found": True, "price": 89.99, "currency": "PLN", "seller": "Example Shop",
            "source_url": "https://example.com/product", "delivery_days": 2, "confidence": 0.85,
        }),
    )
    provider = FirecrawlProvider(api_key="fc-key", groq_api_key="groq-key", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer is not None
    assert offer.price == Decimal("89.99")
    assert offer.citations == ("https://example.com/product",)
    assert client.requests[0]["url"] == SEARCH_API_URL
    assert client.requests[1]["url"] == GROQ_API_URL
    assert client.requests[1]["json"]["response_format"]["type"] == "json_schema"


def test_uses_correct_bearer_key_on_each_call():
    client = _TwoServiceClient(
        search_payload=_search_response([{"title": "t", "description": "d", "url": "https://example.com/x"}]),
        extract_payload=_extract_response({"found": False}),
    )
    provider = FirecrawlProvider(api_key="firecrawl-secret", groq_api_key="groq-secret", client=client)

    provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert client.requests[0]["headers"]["Authorization"] == "Bearer firecrawl-secret"
    assert client.requests[1]["headers"]["Authorization"] == "Bearer groq-secret"


def test_ean_first_query_when_ean_present():
    client = _TwoServiceClient(
        search_payload=_search_response([]),
        extract_payload=_extract_response({"found": False}),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    provider.find_cheapest(
        _make_product(ean="5901234123457", name="Widget"), market="PL", max_delivery_days=5,
    )

    assert client.requests[0]["json"]["query"] == "5901234123457 Widget"


def test_name_only_query_when_ean_absent():
    client = _TwoServiceClient(
        search_payload=_search_response([]),
        extract_payload=_extract_response({"found": False}),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    provider.find_cheapest(_make_product(ean=None, name="Widget"), market="PL", max_delivery_days=5)

    assert client.requests[0]["json"]["query"] == "Widget"


def test_location_present_for_mapped_market():
    client = _TwoServiceClient(
        search_payload=_search_response([]),
        extract_payload=_extract_response({"found": False}),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert client.requests[0]["json"]["location"] == "Poland"


def test_location_absent_for_unmapped_market():
    client = _TwoServiceClient(
        search_payload=_search_response([]),
        extract_payload=_extract_response({"found": False}),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    provider.find_cheapest(_make_product(), market="XX", max_delivery_days=5)

    assert "location" not in client.requests[0]["json"]


def test_returns_none_and_skips_extraction_when_no_web_results():
    client = _TwoServiceClient(
        search_payload=_search_response([]),
        # If _extract were ever called with this payload, offer would be
        # truthy and the "no extraction call attempted" assertion would fail.
        extract_payload=_extract_response({
            "found": True, "price": 1.0, "currency": "PLN", "seller": "S",
            "source_url": "https://example.com", "delivery_days": 1, "confidence": 1.0,
        }),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer is None
    assert len(client.requests) == 1  # only the search call


def test_returns_none_and_skips_extraction_when_data_missing_web_key():
    client = _TwoServiceClient(
        search_payload={"success": True, "data": {}, "creditsUsed": 0},
        extract_payload=_extract_response({
            "found": True, "price": 1.0, "currency": "PLN", "seller": "S",
            "source_url": "https://example.com", "delivery_days": 1, "confidence": 1.0,
        }),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer is None
    assert len(client.requests) == 1


def test_dedupes_citation_urls_across_multiple_search_results():
    client = _TwoServiceClient(
        search_payload=_search_response([
            {"title": "A", "description": "d", "url": "https://example.com/x"},
            {"title": "B", "description": "d", "url": "https://example.com/x"},
            {"title": "C", "description": "d", "url": "https://example.com/y"},
        ]),
        extract_payload=_extract_response({
            "found": True, "price": 5.0, "currency": "PLN", "seller": "S",
            "source_url": "https://example.com/x", "delivery_days": 1, "confidence": 0.5,
        }),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer.citations == ("https://example.com/x", "https://example.com/y")


def test_extract_prompt_includes_search_snippet_text():
    client = _TwoServiceClient(
        search_payload=_search_response([
            {"title": "Example Shop", "description": "Cena: 89.99 zl", "url": "https://example.com/product"},
        ]),
        extract_payload=_extract_response({"found": False}),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    prompt = client.requests[1]["json"]["messages"][0]["content"]
    assert "Example Shop" in prompt
    assert "89.99" in prompt
    assert "https://example.com/product" in prompt


def test_extract_model_constructor_override_is_used_in_extract_call():
    client = _TwoServiceClient(
        search_payload=_search_response([
            {"title": "Example Shop", "description": "89.99 PLN", "url": "https://example.com/product"},
        ]),
        extract_payload=_extract_response({
            "found": True, "price": 89.99, "currency": "PLN", "seller": "Example Shop",
            "source_url": "https://example.com/product", "delivery_days": 2, "confidence": 0.85,
        }),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client, extract_model="custom-model")

    provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert client.requests[1]["json"]["model"] == "custom-model"


class _SearchCallFailsClient:
    def post(self, url, headers, json):
        raise httpx.ConnectError("connection refused")


def test_raises_provider_unavailable_when_search_call_fails():
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=_SearchCallFailsClient())

    with pytest.raises(ProviderUnavailable):
        provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)


class _AuthFailsOnSearchClient:
    def post(self, url, headers, json):
        return _FakeResponse({}, status_code=401)


def test_raises_provider_auth_error_when_search_call_rejects_key():
    provider = FirecrawlProvider(api_key="bad-key", groq_api_key="g", client=_AuthFailsOnSearchClient())

    with pytest.raises(ProviderAuthError):
        provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)


class _AuthFailsOnExtractClient:
    def post(self, url, headers, json):
        if url == SEARCH_API_URL:
            return _FakeResponse(_search_response([
                {"title": "t", "description": "d", "url": "https://example.com/x"},
            ]))
        return _FakeResponse({}, status_code=401)


def test_raises_provider_auth_error_when_extract_call_rejects_key():
    provider = FirecrawlProvider(api_key="k", groq_api_key="bad-key", client=_AuthFailsOnExtractClient())

    with pytest.raises(ProviderAuthError):
        provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)


def test_raises_provider_rate_limited_after_exhausting_retries_on_search(monkeypatch):
    monkeypatch.setattr("app.providers.retry.time.sleep", lambda *_: None)

    class _AlwaysRateLimitedClient:
        def post(self, url, headers, json):
            return _FakeResponse({}, status_code=429)

    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=_AlwaysRateLimitedClient())

    with pytest.raises(ProviderRateLimited):
        provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)


def test_raises_provider_rate_limited_after_exhausting_retries_on_extract(monkeypatch):
    monkeypatch.setattr("app.providers.retry.time.sleep", lambda *_: None)

    class _RateLimitedOnExtractClient:
        def post(self, url, headers, json):
            if url == SEARCH_API_URL:
                return _FakeResponse(_search_response([
                    {"title": "t", "description": "d", "url": "https://example.com/x"},
                ]))
            return _FakeResponse({}, status_code=429)

    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=_RateLimitedOnExtractClient())

    with pytest.raises(ProviderRateLimited):
        provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)
