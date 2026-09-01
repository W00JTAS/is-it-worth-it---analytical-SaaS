from __future__ import annotations

from app.models.product import Product
from app.providers.base import (
    OfferResult,
    PriceProvider,
    ProviderAuthError,
    ProviderProfile,
    ProviderUnavailable,
)


class FallbackProvider:
    """Wraps two `PriceProvider`-shaped objects: tries `primary` first (meant
    to be the free-but-quota-constrained provider), and only consults
    `secondary` (meant to be the costlier but quota-independent provider)
    when primary comes back empty or fails transiently. Deliberately
    provider-agnostic — works with any structurally-conformant PriceProvider,
    not just GroqProvider/FirecrawlProvider.
    """

    def __init__(self, primary: PriceProvider, secondary: PriceProvider):
        self.primary = primary
        self.secondary = secondary
        self.name = f"{primary.name}+{secondary.name}"
        # Approximation for the pre-scan estimate only (see base.py's own
        # ProviderProfile docstring: "never a billing guarantee"). Cost uses
        # secondary's rate as a worst-case upper bound, since the fallback
        # only fires when primary returns nothing/fails — real average cost
        # is lower. seconds_per_query sums both because, in the fallback
        # path, both are actually called sequentially.
        self.profile = ProviderProfile(
            cost_per_query_usd=secondary.profile.cost_per_query_usd,
            seconds_per_query=primary.profile.seconds_per_query + secondary.profile.seconds_per_query,
        )

    def find_cheapest(
        self, product: Product, market: str, max_delivery_days: int
    ) -> OfferResult | None:
        try:
            offer = self.primary.find_cheapest(product, market, max_delivery_days)
        except ProviderAuthError:
            # A bad key means every other in-flight call for this scan will
            # fail identically — propagate immediately rather than masking
            # it behind a fallback, which would silently shift ALL traffic
            # (and cost) to secondary without anyone noticing why.
            raise
        except ProviderUnavailable:
            # Covers ProviderRateLimited too (a subclass) — both are
            # transient failures where primary was never successfully
            # consulted, so fall back to secondary.
            return self.secondary.find_cheapest(product, market, max_delivery_days)

        if offer is not None:
            return offer
        return self.secondary.find_cheapest(product, market, max_delivery_days)
