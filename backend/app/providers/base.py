from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from app.models.product import Product


@dataclass(frozen=True)
class OfferResult:
    price: Decimal
    currency: str
    seller: str
    source_url: str
    delivery_days: int
    confidence: float
    citations: tuple[str, ...]
    raw_response: str


class PriceProvider(Protocol):
    name: str

    def find_cheapest(
        self, product: Product, market: str, max_delivery_days: int
    ) -> OfferResult | None:
        ...
