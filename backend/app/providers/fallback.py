from __future__ import annotations

from app.models.product import Product
from app.providers.base import (
    OfferResult,
    PriceProvider,
    ProviderAuthError,
    ProviderProfile,
    ProviderRateLimited,
    ProviderUnavailable,
)


class FallbackProvider:
    """Wraps two `PriceProvider`-shaped objects: tries `primary` first (meant
    to be the free-but-quota-constrained provider), and only consults
    `secondary` (meant to be the costlier but quota-independent provider)
    when primary comes back empty or fails transiently. Deliberately
    provider-agnostic — works with any structurally-conformant PriceProvider,
    not just GroqProvider/FirecrawlProvider.

    One stateful exception to "try primary first": a ProviderRateLimited from
    primary latches it off permanently for this instance — see find_cheapest
    for why, and for what that would need before production use.
    """

    def __init__(self, primary: PriceProvider, secondary: PriceProvider):
        self.primary = primary
        self.secondary = secondary
        self.name = f"{primary.name}+{secondary.name}"
        # Approximation for the pre-scan estimate only (see base.py's own
        # ProviderProfile docstring: "never a billing guarantee"). Cost sums
        # BOTH rates as a worst-case upper bound: in the fallback path both
        # providers are genuinely called, so a composition of two paid
        # providers really does bill twice for one lookup. (With today's
        # Groq-primary this is numerically identical to secondary's rate
        # alone, since Groq's free tier is Decimal("0.000") — the sum is for
        # correctness when composing two non-free providers.) Real average
        # cost is lower, because primary answering alone skips secondary.
        # seconds_per_query sums both for the same reason.
        self.profile = ProviderProfile(
            cost_per_query_usd=(
                primary.profile.cost_per_query_usd + secondary.profile.cost_per_query_usd
            ),
            seconds_per_query=primary.profile.seconds_per_query + secondary.profile.seconds_per_query,
        )
        # Latch: flipped permanently (for this instance) the first time
        # primary raises ProviderRateLimited — see find_cheapest.
        self._primary_disabled = False
        # Whichever sub-provider actually answered the most recent
        # find_cheapest call, so `last_search_text` can be forwarded to it.
        self._last_used: PriceProvider | None = None

    @property
    def last_search_text(self) -> str | None:
        """Forwards the debugging hook GroqProvider/FirecrawlProvider expose
        (see provider_eval.py's --keep-raw) to whichever sub-provider
        actually answered the most recent find_cheapest call. Without this,
        --keep-raw is a silent no-op for the composed provider: getattr on
        FallbackProvider itself would always find nothing.
        """
        return getattr(self._last_used, "last_search_text", None)

    def find_cheapest(
        self, product: Product, market: str, max_delivery_days: int
    ) -> OfferResult | None:
        if self._primary_disabled:
            # Primary already hit its rate-limit wall on this instance; every
            # further attempt would only re-pay the retry backoff (~60s of
            # sleeping and 4 wasted requests per product) before failing the
            # same way. Go straight to secondary.
            return self._via_secondary(product, market, max_delivery_days)

        try:
            offer = self.primary.find_cheapest(product, market, max_delivery_days)
        except ProviderAuthError:
            # A bad key means every other in-flight call for this scan will
            # fail identically — propagate immediately rather than masking
            # it behind a fallback, which would silently shift ALL traffic
            # (and cost) to secondary without anyone noticing why.
            raise
        except ProviderRateLimited:
            # A rate limit that survived retry.py's backoff is not a
            # per-product hiccup — it means primary's budget is gone (for
            # Groq, the undocumented daily token wall in
            # .claude/rules/groq-compound-free-tier-reliability.md, which
            # does not reopen within a run). Latch primary off for the rest
            # of this instance's life instead of paying the full retry
            # backoff again on every remaining product.
            #
            # Deliberately permanent, with no timed re-enable from
            # retry_after: provider_eval.py builds a fresh FallbackProvider
            # per script run, so "for this instance" == "for this run".
            #
            # ARCHITECTURE NOTE: this means a scan using this provider will
            # silently never re-consult primary after a single rate limit.
            # That is the right trade-off for the eval harness (where the
            # alternative is burning the whole run on backoff sleeps), but
            # before this class is ever wired into production scanning
            # (app/scans/engine.py, app/providers/lookup.py) the latch needs
            # visibility — telemetry, or a surfaced "primary disabled at
            # product N" signal — otherwise a cost/quality regression would
            # be invisible to the operator.
            self._primary_disabled = True
            return self._via_secondary(product, market, max_delivery_days)
        except ProviderUnavailable:
            # A transient failure where primary was never successfully
            # consulted: fall back for this product only, no latch.
            return self._via_secondary(product, market, max_delivery_days)

        if offer is not None:
            self._last_used = self.primary
            return offer
        return self._via_secondary(product, market, max_delivery_days)

    def _via_secondary(
        self, product: Product, market: str, max_delivery_days: int
    ) -> OfferResult | None:
        # _last_used is set BEFORE the call so that last_search_text points
        # at secondary even when secondary raises and the caller inspects it.
        self._last_used = self.secondary
        return self.secondary.find_cheapest(product, market, max_delivery_days)
