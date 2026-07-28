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


class ProviderUnavailable(Exception):
    """Raised by a PriceProvider when it could not be reached or failed transiently.

    Covers network errors, timeouts, and non-2xx HTTP responses (e.g. 429/5xx) —
    situations where the provider was never actually consulted successfully, as
    opposed to a genuine negative result (the provider WAS consulted and found no
    valid offer). Callers must treat this distinctly from a `None` return: a
    `None` is a legitimate "no offer found" that is safe to cache, whereas
    `ProviderUnavailable` means the lookup should be retried later and must NOT
    be persisted as a negative cache entry.
    """


class PriceProvider(Protocol):
    name: str

    def find_cheapest(
        self, product: Product, market: str, max_delivery_days: int
    ) -> OfferResult | None:
        """Find the cheapest currently-buyable offer for `product` in `market`.

        Returns `None` when the provider was successfully consulted but found no
        valid offer (e.g. nothing matched, or the answer failed validation).

        Raises `ProviderUnavailable` when the provider itself could not be
        reached or failed transiently (network error, timeout, non-2xx HTTP
        status) — this is NOT a legitimate negative result and must not be
        cached as one.
        """
        ...
