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

    def __init__(self, name: str, outcome, cost: str = "0.000", seconds: float = 1.0,
                 search_text: str | None = None):
        self.name = name
        self.profile = ProviderProfile(cost_per_query_usd=Decimal(cost), seconds_per_query=seconds)
        self._outcome = outcome
        self.call_count = 0
        # Mirrors GroqProvider/FirecrawlProvider's --keep-raw debugging hook.
        self._search_text = search_text
        self.last_search_text: str | None = None

    def find_cheapest(self, product, market, max_delivery_days):
        self.call_count += 1
        self.last_search_text = self._search_text
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


def test_profile_sums_both_costs_and_seconds():
    primary = _FakeProvider("groq", None, cost="0.000", seconds=4.0)
    secondary = _FakeProvider("firecrawl", None, cost="0.0017", seconds=5.0)
    provider = FallbackProvider(primary, secondary)

    # Groq's free tier is 0.000, so today this is numerically identical to
    # secondary's cost alone — the sum is what keeps it correct when two
    # non-free providers are composed.
    assert provider.profile.cost_per_query_usd == Decimal("0.0017")
    assert provider.profile.seconds_per_query == pytest.approx(9.0)


def test_profile_cost_sums_both_when_both_providers_cost_money():
    primary = _FakeProvider("paid-a", None, cost="0.0030", seconds=4.0)
    secondary = _FakeProvider("paid-b", None, cost="0.0017", seconds=5.0)
    provider = FallbackProvider(primary, secondary)

    assert provider.profile.cost_per_query_usd == Decimal("0.0047")


def test_rate_limit_on_primary_falls_back_and_latches_primary_off():
    # After Groq's daily wall fires, retrying primary on every remaining
    # product only re-pays the retry backoff (~60s of sleeping, 4 wasted
    # requests) before failing identically — so the first ProviderRateLimited
    # must disable primary for the rest of this instance's life.
    primary = _FakeProvider("primary", ProviderRateLimited("daily wall", retry_after=1800.0))
    secondary_offer = _make_offer("Secondary Seller")
    secondary = _FakeProvider("secondary", secondary_offer)
    provider = FallbackProvider(primary, secondary)

    first = provider.find_cheapest(_make_product(), "PL", 5)

    assert first is secondary_offer
    assert primary.call_count == 1
    assert secondary.call_count == 1
    assert provider._primary_disabled is True

    second = provider.find_cheapest(_make_product(), "PL", 5)

    assert second is secondary_offer
    assert primary.call_count == 1  # primary never touched again
    assert secondary.call_count == 2


def test_reset_re_enables_primary_after_a_latch():
    # A caller that reuses one FallbackProvider instance across multiple
    # logical runs (e.g. app.scans.api's process-wide singleton, reused
    # across every scan) must be able to give primary a fresh chance each
    # run -- otherwise one rate limit anywhere permanently shifts every
    # later run onto secondary for the life of the process.
    primary = _FakeProvider("primary", ProviderRateLimited("daily wall", retry_after=1800.0))
    secondary_offer = _make_offer("Secondary Seller")
    secondary = _FakeProvider("secondary", secondary_offer)
    provider = FallbackProvider(primary, secondary)

    provider.find_cheapest(_make_product(), "PL", 5)
    assert provider._primary_disabled is True

    provider.reset()
    assert provider._primary_disabled is False

    primary._outcome = _make_offer("Primary Seller")  # primary "recovered"
    result = provider.find_cheapest(_make_product(), "PL", 5)

    assert result.seller == "Primary Seller"
    assert primary.call_count == 2  # consulted again after reset, not skipped


def test_plain_provider_unavailable_does_not_latch_primary_off():
    # Only a rate limit means "primary's budget is gone". An ordinary
    # transient failure (timeout, 5xx) must still let the next product try
    # primary first, or one blip would permanently shift all traffic to the
    # costlier secondary.
    primary = _FakeProvider("primary", ProviderUnavailable("timeout"))
    secondary = _FakeProvider("secondary", _make_offer("Secondary Seller"))
    provider = FallbackProvider(primary, secondary)

    provider.find_cheapest(_make_product(), "PL", 5)
    provider.find_cheapest(_make_product(), "PL", 5)

    assert provider._primary_disabled is False
    assert primary.call_count == 2
    assert secondary.call_count == 2


def test_last_search_text_forwards_to_primary_when_primary_answered():
    primary = _FakeProvider("primary", _make_offer(), search_text="primary raw text")
    secondary = _FakeProvider("secondary", None, search_text="secondary raw text")
    provider = FallbackProvider(primary, secondary)

    provider.find_cheapest(_make_product(), "PL", 5)

    assert provider.last_search_text == "primary raw text"


def test_last_search_text_forwards_to_secondary_when_secondary_answered():
    primary = _FakeProvider("primary", None, search_text="primary raw text")
    secondary = _FakeProvider("secondary", _make_offer(), search_text="secondary raw text")
    provider = FallbackProvider(primary, secondary)

    provider.find_cheapest(_make_product(), "PL", 5)

    assert provider.last_search_text == "secondary raw text"


def test_last_search_text_is_none_before_any_call_and_for_providers_without_the_hook():
    class _NoHookProvider(_FakeProvider):
        """A provider that never exposes last_search_text at all — e.g. the
        Gemini spike client in provider_eval.py."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            del self.last_search_text

        def find_cheapest(self, product, market, max_delivery_days):
            self.call_count += 1
            return self._outcome

    provider = FallbackProvider(
        _NoHookProvider("primary", _make_offer()), _FakeProvider("secondary", None),
    )

    assert provider.last_search_text is None  # nothing called yet

    provider.find_cheapest(_make_product(), "PL", 5)

    assert provider.last_search_text is None  # primary has no such attribute
