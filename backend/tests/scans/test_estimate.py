from decimal import Decimal

from app.scans.estimate import COST_PER_QUERY_USD, SECONDS_PER_QUERY, estimate_cost


def test_estimate_with_no_misses_and_no_stale_is_free_and_instant():
    result = estimate_cost(cache_misses=0, stale_count=0, max_concurrency=5)

    assert result.queries_without_refresh == 0
    assert result.queries_with_refresh == 0
    assert result.cost_usd_without_refresh == Decimal("0.00")
    assert result.cost_usd_with_refresh == Decimal("0.00")
    assert result.seconds_without_refresh == 0.0
    assert result.seconds_with_refresh == 0.0


def test_estimate_scales_with_query_count_and_concurrency():
    result = estimate_cost(cache_misses=100, stale_count=20, max_concurrency=10)

    assert result.queries_without_refresh == 100
    assert result.queries_with_refresh == 120
    assert result.cost_usd_without_refresh == (COST_PER_QUERY_USD * 100).quantize(Decimal("0.01"))
    assert result.cost_usd_with_refresh == (COST_PER_QUERY_USD * 120).quantize(Decimal("0.01"))
    assert result.seconds_without_refresh == (100 / 10) * SECONDS_PER_QUERY
    assert result.seconds_with_refresh == (120 / 10) * SECONDS_PER_QUERY


def test_estimate_with_refresh_is_never_cheaper_than_without():
    result = estimate_cost(cache_misses=50, stale_count=5, max_concurrency=5)

    assert result.queries_with_refresh >= result.queries_without_refresh
    assert result.cost_usd_with_refresh >= result.cost_usd_without_refresh
    assert result.seconds_with_refresh >= result.seconds_without_refresh
