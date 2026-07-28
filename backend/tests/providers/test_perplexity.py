import json
from decimal import Decimal

import pytest

from app.models.product import Product
from app.providers.perplexity import PerplexityProvider


def _make_product(**overrides) -> Product:
    defaults = dict(
        tenant_id="t1", source="csv", external_id="1", variant_id=None,
        name="Test Product", ean="5901234123457",
        wholesale_price=Decimal("60.00"), currency="PLN", category="Test",
    )
    defaults.update(overrides)
    return Product(**defaults)


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, content: dict | None, citations: list[str] | None = None):
        self._content = content
        self._citations = citations or []
        self.last_request: dict | None = None

    def post(self, url, headers, json):
        self.last_request = {"url": url, "headers": headers, "json": json}
        return _FakeResponse(
            {
                "choices": [{"message": {"content": __import__("json").dumps(self._content)}}],
                "citations": self._citations,
            }
        )


def test_returns_offer_for_a_valid_found_response():
    client = _FakeClient(
        content={
            "found": True,
            "price": 89.99,
            "currency": "PLN",
            "seller": "Example Shop",
            "source_url": "https://example.com/product",
            "delivery_days": 2,
            "confidence": 0.85,
        },
        citations=["https://example.com/product"],
    )
    provider = PerplexityProvider(api_key="test-key", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer is not None
    assert offer.price == Decimal("89.99")
    assert offer.currency == "PLN"
    assert offer.seller == "Example Shop"
    assert offer.source_url == "https://example.com/product"
    assert offer.delivery_days == 2
    assert offer.confidence == 0.85
    assert offer.citations == ("https://example.com/product",)
    assert json.loads(offer.raw_response)["citations"] == ["https://example.com/product"]


def test_sends_bearer_auth_and_json_schema_response_format():
    client = _FakeClient(content={"found": False})
    provider = PerplexityProvider(api_key="secret-key", client=client)

    provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert client.last_request["headers"]["Authorization"] == "Bearer secret-key"
    assert client.last_request["json"]["response_format"]["type"] == "json_schema"
    assert client.last_request["json"]["model"] == "sonar"


def test_returns_none_when_not_found():
    client = _FakeClient(content={"found": False})
    provider = PerplexityProvider(api_key="test-key", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer is None


def test_returns_none_when_source_url_missing():
    client = _FakeClient(
        content={
            "found": True, "price": 10.0, "currency": "PLN", "seller": "X",
            "source_url": "", "delivery_days": 2, "confidence": 0.9,
        }
    )
    provider = PerplexityProvider(api_key="test-key", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer is None


def test_returns_none_when_delivery_exceeds_limit():
    client = _FakeClient(
        content={
            "found": True, "price": 10.0, "currency": "PLN", "seller": "X",
            "source_url": "https://example.com/x", "delivery_days": 20, "confidence": 0.9,
        }
    )
    provider = PerplexityProvider(api_key="test-key", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer is None


def test_returns_none_on_malformed_content():
    client = _FakeClient(content=None)  # json.dumps(None) -> "null" -> parses to None, not a dict
    provider = PerplexityProvider(api_key="test-key", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer is None
