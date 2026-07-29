from __future__ import annotations

from decimal import Decimal

from app.scans.models import CostEstimate

# Documented assumption, not a measured guarantee — Perplexity's own published
# range is $5-14 per 1000 requests plus token cost (see the Phase 3 design
# spec's research notes); this is a conservative midpoint used only to give
# the user a ballpark before they commit to a scan, not a billing guarantee.
COST_PER_QUERY_USD = Decimal("0.010")

# Rough average latency observed during Phase 3's real Perplexity smoke test
# (~2.36s for one request); used only for the pre-scan time estimate, not a
# guaranteed throughput figure.
SECONDS_PER_QUERY = 2.5


def estimate_cost(cache_misses: int, stale_count: int, max_concurrency: int) -> CostEstimate:
    queries_without_refresh = cache_misses
    queries_with_refresh = cache_misses + stale_count

    return CostEstimate(
        queries_without_refresh=queries_without_refresh,
        queries_with_refresh=queries_with_refresh,
        cost_usd_without_refresh=(COST_PER_QUERY_USD * queries_without_refresh).quantize(Decimal("0.01")),
        cost_usd_with_refresh=(COST_PER_QUERY_USD * queries_with_refresh).quantize(Decimal("0.01")),
        seconds_without_refresh=(queries_without_refresh / max_concurrency) * SECONDS_PER_QUERY,
        seconds_with_refresh=(queries_with_refresh / max_concurrency) * SECONDS_PER_QUERY,
    )
