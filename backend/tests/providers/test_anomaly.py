from decimal import Decimal

from app.providers.anomaly import AnomalyFlag, detect_anomaly
from app.providers.base import OfferResult


def _make_offer(**overrides) -> OfferResult:
    defaults = dict(
        price=Decimal("100.00"),
        currency="PLN",
        seller="Example Shop",
        source_url="https://example.com/product",
        delivery_days=3,
        confidence=0.9,
        citations=("https://example.com/product",),
        raw_response="{}",
    )
    defaults.update(overrides)
    return OfferResult(**defaults)


def test_no_anomaly_for_reasonable_offer():
    offer = _make_offer(price=Decimal("100.00"), confidence=0.9)
    assert detect_anomaly(offer, wholesale_price=Decimal("60.00")) is None


def test_flags_price_below_wholesale():
    offer = _make_offer(price=Decimal("50.00"), confidence=0.9)
    assert detect_anomaly(offer, wholesale_price=Decimal("60.00")) == AnomalyFlag.BELOW_WHOLESALE


def test_flags_unusually_high_price():
    offer = _make_offer(price=Decimal("1000.00"), confidence=0.9)
    assert detect_anomaly(offer, wholesale_price=Decimal("60.00")) == AnomalyFlag.UNUSUALLY_HIGH


def test_flags_low_confidence_before_price_checks():
    offer = _make_offer(price=Decimal("50.00"), confidence=0.2)
    assert detect_anomaly(offer, wholesale_price=Decimal("60.00")) == AnomalyFlag.LOW_CONFIDENCE
