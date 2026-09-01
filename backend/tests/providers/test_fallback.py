from decimal import Decimal

import pytest

from app.models.product import Product
from app.providers.base import (
    OfferResult,
    ProviderAuthError,
    ProviderProfile,
    ProviderRateLimited,
    ProviderUnavailable,
)
from app.providers.fallback import FallbackProvider


def _make_product() -> Product:
    return Product(
        tenant_id="eval", source="csv", external_id="SKU1", variant_id=None,
        name="Product 1", ean=None, wholesale_price=Decimal("10.00"),
        currency="PLN", category="Test",
    )


def _make_offer(seller: str = "Seller") -> OfferResult:
    return OfferResult(
        price=Decimal("9.99"), currency="PLN", seller=seller,
        source_url="https://example.com", delivery_days=1, confidence=0.9,
        citations=(), raw_response="raw",
    )


class _FakeProvider:
    """Hand-written PriceProvider-shaped fake — no real Groq/Firecrawl
    instance needed. `outcome` is either an OfferResult, None, or an
    Exception instance to raise. Records call count so tests can assert
    on whether secondary was ever consulted.
    """

    def __init__(self, name: str, outcome, cost: str = "0.000", seconds: float = 1.0):
        self.name = name
        self.profile = ProviderProfile(cost_per_query_usd=Decimal(cost), seconds_per_query=seconds)
        self._outcome = outcome
        self.call_count = 0

    def find_cheapest(self, product, market, max_delivery_days):
        self.call_count += 1
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


def test_primary_found_returns_directly_without_calling_secondary():
    offer = _make_offer("Primary Seller")
    primary = _FakeProvider("primary", offer)
    secondary = _FakeProvider("secondary", _make_offer("Secondary Seller"))
    provider = FallbackProvider(primary, secondary)

    result = provider.find_cheapest(_make_product(), "PL", 5)

    assert result is offer
    assert primary.call_count == 1
    assert secondary.call_count == 0


def test_primary_none_falls_back_to_secondary_found():
    primary = _FakeProvider("primary", None)
    secondary_offer = _make_offer("Secondary Seller")
    secondary = _FakeProvider("secondary", secondary_offer)
    provider = FallbackProvider(primary, secondary)

    result = provider.find_cheapest(_make_product(), "PL", 5)

    assert result is secondary_offer
    assert primary.call_count == 1
    assert secondary.call_count == 1


def test_primary_none_falls_back_to_secondary_also_none():
    primary = _FakeProvider("primary", None)
    secondary = _FakeProvider("secondary", None)
    provider = FallbackProvider(primary, secondary)

    result = provider.find_cheapest(_make_product(), "PL", 5)

    assert result is None
    assert primary.call_count == 1
    assert secondary.call_count == 1


def test_primary_provider_unavailable_falls_back_to_secondary():
    primary = _FakeProvider("primary", ProviderUnavailable("transient failure"))
    secondary_offer = _make_offer("Secondary Seller")
    secondary = _FakeProvider("secondary", secondary_offer)
    provider = FallbackProvider(primary, secondary)

    result = provider.find_cheapest(_make_product(), "PL", 5)

    assert result is secondary_offer
    assert primary.call_count == 1
    assert secondary.call_count == 1


def test_primary_provider_rate_limited_subclass_also_falls_back():
    primary = _FakeProvider("primary", ProviderRateLimited("rate limited", retry_after=12.0))
    secondary_offer = _make_offer("Secondary Seller")
    secondary = _FakeProvider("secondary", secondary_offer)
    provider = FallbackProvider(primary, secondary)

    result = provider.find_cheapest(_make_product(), "PL", 5)

    assert result is secondary_offer
    assert primary.call_count == 1
    assert secondary.call_count == 1


def test_primary_auth_error_propagates_without_calling_secondary():
    primary = _FakeProvider("primary", ProviderAuthError("bad key"))
    secondary = _FakeProvider("secondary", _make_offer())
    provider = FallbackProvider(primary, secondary)

    with pytest.raises(ProviderAuthError):
        provider.find_cheapest(_make_product(), "PL", 5)

    assert primary.call_count == 1
    assert secondary.call_count == 0


def test_secondary_exception_propagates_uncaught():
    primary = _FakeProvider("primary", None)
    secondary = _FakeProvider("secondary", ProviderUnavailable("secondary also down"))
    provider = FallbackProvider(primary, secondary)

    with pytest.raises(ProviderUnavailable):
        provider.find_cheapest(_make_product(), "PL", 5)

    assert primary.call_count == 1
    assert secondary.call_count == 1


def test_name_is_primary_plus_secondary():
    primary = _FakeProvider("groq", None)
    secondary = _FakeProvider("firecrawl", None)
    provider = FallbackProvider(primary, secondary)

    assert provider.name == "groq+firecrawl"


def test_profile_uses_secondary_cost_and_summed_seconds():
    primary = _FakeProvider("groq", None, cost="0.000", seconds=4.0)
    secondary = _FakeProvider("firecrawl", None, cost="0.0017", seconds=5.0)
    provider = FallbackProvider(primary, secondary)

    assert provider.profile.cost_per_query_usd == Decimal("0.0017")
    assert provider.profile.seconds_per_query == pytest.approx(9.0)
