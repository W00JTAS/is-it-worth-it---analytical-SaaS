from __future__ import annotations

import logging

from app.models.product import Product
from app.providers.base import (
    OfferResult,
    PriceProvider,
    ProviderAuthError,
    ProviderProfile,
    ProviderRateLimited,
    ProviderUnavailable,
)

logger = logging.getLogger(__name__)


class FallbackProvider:
    """Wraps two `PriceProvider`-shaped objects: tries `primary` first (meant
    to be the free-but-quota-constrained provider), and only consults
    `secondary` when primary comes back empty or fails transiently.
    Deliberately provider-agnostic — works with any structurally-conformant
    PriceProvider, not just GroqProvider/FirecrawlProvider.

    `secondary` is NOT necessarily quota-independent of `primary` — with
    today's GroqProvider+FirecrawlProvider composition it explicitly is not:
    FirecrawlProvider._extract calls the same Groq extraction model
    (gpt-oss-20b) GroqProvider._extract does, so the two sub-providers share
    that model's daily token budget even though only `primary`'s SEARCH step
    (compound-mini) is genuinely independent.

    One stateful exception to "try primary first": a ProviderRateLimited from
    primary latches it off for this instance — see find_cheapest for why —
    until `reset()` is called. Call `reset()` once per logical "run" (e.g.
    once per scan, not once per process): the latch was designed around
    provider_eval.py's one-shot CLI usage, where "for this instance" and
    "for this run" were the same thing. A caller that keeps one
    FallbackProvider instance alive across many runs (e.g. a long-lived
    server process reusing it via a module-level singleton) MUST call
    `reset()` at the start of each run, or a single rate limit anywhere
    permanently and silently shifts every later run onto the costlier
    secondary for the rest of the process's uptime.
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

    def reset(self) -> None:
        """Re-enables primary if a prior run's rate limit had latched it
        off. Callers that reuse one FallbackProvider instance across
        multiple logical runs (see class docstring) must call this at the
        start of each run — otherwise the latch, designed for a one-shot
        script's lifetime, silently outlives the run that tripped it.
        """
        self._primary_disabled = False

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
            # Groq, an undocumented daily token wall that sits well below
            # the documented 250 requests/day and does not reopen within a
            # run). Latch primary off for the rest
            # of this instance's life instead of paying the full retry
            # backoff again on every remaining product.
            #
            # Deliberately permanent for the rest of THIS run, with no timed
            # re-enable from retry_after: paying the full retry backoff
            # again on every remaining product would burn the whole run for
            # no better odds. Callers that reuse one instance across
            # multiple runs (see class docstring) must call reset() between
            # runs — app/scans/engine.py's run_scan does this at the start
            # of every scan, so the latch doesn't outlive the run that
            # tripped it. Also logged (below), so an operator watching logs
            # can see the cost/quality shift instead of it being invisible.
            logger.warning(
                "%s rate-limited; disabling it for the rest of this run, "
                "falling back to %s for every remaining lookup",
                self.primary.name, self.secondary.name,
            )
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
