import dataclasses
from decimal import Decimal

from app.providers.base import OfferResult, ProviderAuthError, ProviderProfile, ProviderRateLimited, ProviderUnavailable


def _make_offer(**overrides) -> OfferResult:
    defaults = dict(
        price=Decimal("99.99"),
        currency="PLN",
        seller="Example Shop",
        source_url="https://example.com/product",
        delivery_days=3,
        confidence=0.9,
        citations=("https://example.com/product",),
        raw_response='{"raw": true}',
    )
    defaults.update(overrides)
    return OfferResult(**defaults)


def test_offer_result_holds_all_contract_fields():
    offer = _make_offer()
    assert offer.price == Decimal("99.99")
    assert offer.currency == "PLN"
    assert offer.seller == "Example Shop"
    assert offer.source_url == "https://example.com/product"
    assert offer.delivery_days == 3
    assert offer.confidence == 0.9
    assert offer.citations == ("https://example.com/product",)
    assert offer.raw_response == '{"raw": true}'


def test_offer_result_is_frozen():
    offer = _make_offer()
    with __import__("pytest").raises(dataclasses.FrozenInstanceError):
        offer.price = Decimal("1.00")


def test_provider_profile_holds_cost_and_timing():
    profile = ProviderProfile(cost_per_query_usd=Decimal("0.010"), seconds_per_query=2.5)
    assert profile.cost_per_query_usd == Decimal("0.010")
    assert profile.seconds_per_query == 2.5


def test_provider_rate_limited_is_a_provider_unavailable_and_carries_retry_after():
    exc = ProviderRateLimited("rate limited", retry_after=30.0)
    assert isinstance(exc, ProviderUnavailable)
    assert exc.retry_after == 30.0


def test_provider_rate_limited_retry_after_defaults_to_none():
    exc = ProviderRateLimited("rate limited")
    assert exc.retry_after is None


def test_provider_auth_error_is_not_a_provider_unavailable():
    # Deliberate: an auth error must never be treated as "retry me later" —
    # it must abort the whole scan, not leave the record pending.
    assert not issubclass(ProviderAuthError, ProviderUnavailable)
