from __future__ import annotations

from decimal import Decimal

from app.providers.base import ProviderProfile
from app.scans.models import CostEstimate


def estimate_cost(
    cache_misses: int, stale_count: int, max_concurrency: int, profile: ProviderProfile
) -> CostEstimate:
    queries_without_refresh = cache_misses
    queries_with_refresh = cache_misses + stale_count

    return CostEstimate(
        queries_without_refresh=queries_without_refresh,
        queries_with_refresh=queries_with_refresh,
        cost_usd_without_refresh=(profile.cost_per_query_usd * queries_without_refresh).quantize(Decimal("0.01")),
        cost_usd_with_refresh=(profile.cost_per_query_usd * queries_with_refresh).quantize(Decimal("0.01")),
        seconds_without_refresh=(queries_without_refresh / max_concurrency) * profile.seconds_per_query,
        seconds_with_refresh=(queries_with_refresh / max_concurrency) * profile.seconds_per_query,
    )
