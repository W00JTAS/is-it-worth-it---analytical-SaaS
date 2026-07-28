from __future__ import annotations

from decimal import Decimal
from enum import Enum

from app.providers.base import OfferResult

LOW_CONFIDENCE_THRESHOLD = 0.5
HIGH_PRICE_MULTIPLIER = Decimal("10")


class AnomalyFlag(str, Enum):
    BELOW_WHOLESALE = "below_wholesale"
    UNUSUALLY_HIGH = "unusually_high"
    LOW_CONFIDENCE = "low_confidence"


def detect_anomaly(offer: OfferResult, wholesale_price: Decimal) -> AnomalyFlag | None:
    if offer.confidence < LOW_CONFIDENCE_THRESHOLD:
        return AnomalyFlag.LOW_CONFIDENCE
    if offer.price < wholesale_price:
        return AnomalyFlag.BELOW_WHOLESALE
    if offer.price > wholesale_price * HIGH_PRICE_MULTIPLIER:
        return AnomalyFlag.UNUSUALLY_HIGH
    return None
