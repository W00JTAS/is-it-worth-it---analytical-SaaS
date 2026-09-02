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


@dataclass(frozen=True)
class ProviderProfile:
    """Cost/timing characteristics used only for the pre-scan estimate shown
    to the user (see app/scans/estimate.py) — never a billing guarantee.
    Provider-specific because Perplexity and Groq have unrelated cost/speed
    profiles; RPM/RPD budget fields are deliberately NOT here yet — nothing
    in Faza 1 consumes them, they arrive with Faza 4's provider_usage ledger.
    """

    cost_per_query_usd: Decimal
    seconds_per_query: float


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


class ProviderRateLimited(ProviderUnavailable):
    """Raised when the provider's rate limit is exhausted after retrying
    (see app/providers/retry.py). A subclass of ProviderUnavailable — like
    it, this is transient and the record should stay pending for a later
    resume — but run_scan distinguishes it to pause the WHOLE scan rather
    than only skip this one product, since a rate limit exhausted on one
    call means every other in-flight call will fail identically.
    """

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class ProviderAuthError(Exception):
    """Raised when the provider rejects the API key outright (HTTP 401/403).
    Deliberately NOT a ProviderUnavailable subclass: retrying a bad key
    never helps, and every other in-flight call for this scan will fail
    identically, so run_scan must abort the scan immediately instead of
    leaving 17,500 products cycling through retries one at a time.

    Only guaranteed for providers whose HTTP calls route through
    app.providers.retry.call_with_retry — that is where 401/403 is
    classified. A provider that does its own HTTP error handling instead
    (PerplexityProvider) classifies every non-2xx as ProviderUnavailable and
    cannot raise this. Deliberately not listing which providers are in which
    group: that list goes stale every time one is added.
    """


class PriceProvider(Protocol):
    name: str
    profile: ProviderProfile

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
