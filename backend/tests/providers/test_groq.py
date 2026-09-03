import json
from decimal import Decimal

import httpx
import pytest

from app.models.product import Product
from app.providers.base import ProviderAuthError, ProviderUnavailable
from app.providers.groq import EXTRACT_MAX_TOKENS, EXTRACT_REASONING_EFFORT, GroqProvider


def _make_product(**overrides) -> Product:
    defaults = dict(
        tenant_id="t1", source="csv", external_id="1", variant_id=None,
        name="Test Product", ean="5901234123457",
        wholesale_price=Decimal("60.00"), currency="PLN", category="Test",
    )
    defaults.update(overrides)
    return Product(**defaults)


def _search_response(content: str, search_results: list[dict] | None = None) -> dict:
    message: dict = {"content": content}
    if search_results is not None:
        message["executed_tools"] = [{"search_results": {"results": search_results}}]
    return {"choices": [{"message": message}]}


def _extract_response(parsed: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(parsed)}}]}


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


class _TwoCallClient:
    """Returns `search_payload` for the compound-mini call, `extract_payload`
    for the gpt-oss-20b call, distinguishing by the requested `model`."""

    def __init__(self, search_payload: dict, extract_payload: dict):
        self._search_payload = search_payload
        self._extract_payload = extract_payload
        self.requests: list[dict] = []

    def post(self, url, headers, json):
        self.requests.append({"url": url, "headers": headers, "json": json})
        if json["model"] == "groq/compound-mini":
            return _FakeResponse(self._search_payload)
        return _FakeResponse(self._extract_payload)


def test_two_call_flow_returns_offer_with_citations_from_search_results():
    client = _TwoCallClient(
        search_payload=_search_response(
            "The cheapest offer is 89.99 PLN at Example Shop.",
            search_results=[
                {"title": "Example Shop", "url": "https://example.com/product", "content": "...", "score": 0.9},
            ],
        ),
        extract_payload=_extract_response({
            "found": True, "price": 89.99, "currency": "PLN", "seller": "Example Shop",
            "source_url": "https://example.com/product", "delivery_days": 2, "confidence": 0.85,
        }),
    )
    provider = GroqProvider(api_key="test-key", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer is not None
    assert offer.price == Decimal("89.99")
    assert offer.citations == ("https://example.com/product",)
    # First call uses compound-mini with no response_format (tool use + structured
    # outputs are documented as incompatible); second uses gpt-oss-20b with one.
    assert client.requests[0]["json"]["model"] == "groq/compound-mini"
    assert "response_format" not in client.requests[0]["json"]
    assert client.requests[1]["json"]["model"] == "openai/gpt-oss-20b"
    assert client.requests[1]["json"]["response_format"]["type"] == "json_schema"


def test_uses_bearer_auth_on_both_calls():
    client = _TwoCallClient(
        search_payload=_search_response("no offer found"),
        extract_payload=_extract_response({"found": False}),
    )
    provider = GroqProvider(api_key="secret-key", client=client)

    provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert all(r["headers"]["Authorization"] == "Bearer secret-key" for r in client.requests)


def test_returns_none_when_extract_says_not_found():
    client = _TwoCallClient(
        search_payload=_search_response("Nothing matched."),
        extract_payload=_extract_response({"found": False}),
    )
    provider = GroqProvider(api_key="test-key", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer is None


def test_returns_none_when_no_executed_tools_present():
    # The model may answer from its own knowledge without calling web search;
    # executed_tools is then absent entirely, not an empty list.
    client = _TwoCallClient(
        search_payload=_search_response("I don't have current pricing."),
        extract_payload=_extract_response({"found": False}),
    )
    provider = GroqProvider(api_key="test-key", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer is None  # must not raise on missing executed_tools


def test_deduplicates_citation_urls_across_multiple_search_results():
    client = _TwoCallClient(
        search_payload=_search_response(
            "text",
            search_results=[
                {"title": "A", "url": "https://example.com/x", "content": "", "score": 0.9},
                {"title": "B", "url": "https://example.com/x", "content": "", "score": 0.5},
                {"title": "C", "url": "https://example.com/y", "content": "", "score": 0.4},
            ],
        ),
        extract_payload=_extract_response({
            "found": True, "price": 5.0, "currency": "PLN", "seller": "S",
            "source_url": "https://example.com/x", "delivery_days": 1, "confidence": 0.5,
        }),
    )
    provider = GroqProvider(api_key="test-key", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer.citations == ("https://example.com/x", "https://example.com/y")


class _SearchCallFailsClient:
    def post(self, url, headers, json):
        raise httpx.ConnectError("connection refused")


def test_raises_provider_unavailable_when_search_call_fails():
    provider = GroqProvider(api_key="test-key", client=_SearchCallFailsClient())

    with pytest.raises(ProviderUnavailable):
        provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)


class _AuthFailsOnExtractClient:
    def post(self, url, headers, json):
        if json["model"] == "groq/compound-mini":
            return _FakeResponse(_search_response("some text"))
        return _FakeResponse({}, status_code=401)


def test_raises_provider_auth_error_when_extract_call_rejects_key():
    provider = GroqProvider(api_key="bad-key", client=_AuthFailsOnExtractClient())

    with pytest.raises(ProviderAuthError):
        provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)


class _MalformedSearchContentClient:
    def post(self, url, headers, json):
        return _FakeResponse({"choices": [{}]})  # no "message" key at all


def test_returns_none_on_malformed_search_response():
    provider = GroqProvider(api_key="test-key", client=_MalformedSearchContentClient())

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer is None


def test_search_settings_country_boost_present_for_mapped_market():
    client = _TwoCallClient(
        search_payload=_search_response("no offer found"),
        extract_payload=_extract_response({"found": False}),
    )
    provider = GroqProvider(api_key="test-key", client=client)

    provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert client.requests[0]["json"]["search_settings"] == {"country": "poland"}


def test_search_settings_absent_for_unmapped_market():
    client = _TwoCallClient(
        search_payload=_search_response("no offer found"),
        extract_payload=_extract_response({"found": False}),
    )
    provider = GroqProvider(api_key="test-key", client=client)

    provider.find_cheapest(_make_product(), market="XX", max_delivery_days=5)

    assert "search_settings" not in client.requests[0]["json"]


def test_search_call_includes_positive_max_tokens():
    client = _TwoCallClient(
        search_payload=_search_response("no offer found"),
        extract_payload=_extract_response({"found": False}),
    )
    provider = GroqProvider(api_key="test-key", client=client)

    provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    max_tokens = client.requests[0]["json"]["max_tokens"]
    assert isinstance(max_tokens, int)
    assert max_tokens > 0


def test_extract_call_includes_max_tokens_and_reasoning_effort():
    client = _TwoCallClient(
        search_payload=_search_response("no offer found"),
        extract_payload=_extract_response({"found": False}),
    )
    provider = GroqProvider(api_key="test-key", client=client)

    provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    extract_body = client.requests[1]["json"]
    assert extract_body["max_tokens"] == EXTRACT_MAX_TOKENS
    assert extract_body["reasoning_effort"] == EXTRACT_REASONING_EFFORT


def test_extract_model_constructor_override_is_used_in_extract_call():
    client = _TwoCallClient(
        search_payload=_search_response(
            "The cheapest offer is 89.99 PLN at Example Shop.",
            search_results=[
                {"title": "Example Shop", "url": "https://example.com/product", "content": "...", "score": 0.9},
            ],
        ),
        extract_payload=_extract_response({
            "found": True, "price": 89.99, "currency": "PLN", "seller": "Example Shop",
            "source_url": "https://example.com/product", "delivery_days": 2, "confidence": 0.85,
        }),
    )
    provider = GroqProvider(api_key="test-key", client=client, extract_model="custom-model")

    provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert client.requests[1]["json"]["model"] == "custom-model"


def test_returns_none_citations_when_search_results_results_field_is_none():
    # SDK types search_results.results as Optional — must not crash when it's
    # None (e.g. the tool ran but found nothing) rather than an empty list.
    client = _TwoCallClient(
        search_payload={
            "choices": [{"message": {
                "content": "no offer found",
                "executed_tools": [{"search_results": {"results": None}}],
            }}]
        },
        extract_payload=_extract_response({"found": False}),
    )
    provider = GroqProvider(api_key="test-key", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer is None  # must not raise
