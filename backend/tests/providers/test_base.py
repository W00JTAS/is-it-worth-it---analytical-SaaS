import dataclasses
from decimal import Decimal

from app.providers.base import OfferResult


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
