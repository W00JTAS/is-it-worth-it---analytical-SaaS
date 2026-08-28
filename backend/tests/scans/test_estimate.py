from decimal import Decimal

from app.providers.base import ProviderProfile
from app.scans.estimate import estimate_cost

PROFILE = ProviderProfile(cost_per_query_usd=Decimal("0.010"), seconds_per_query=2.5)


def test_estimate_with_no_misses_and_no_stale_is_free_and_instant():
    result = estimate_cost(cache_misses=0, stale_count=0, max_concurrency=5, profile=PROFILE)

    assert result.queries_without_refresh == 0
    assert result.queries_with_refresh == 0
    assert result.cost_usd_without_refresh == Decimal("0.00")
    assert result.cost_usd_with_refresh == Decimal("0.00")
    assert result.seconds_without_refresh == 0.0
    assert result.seconds_with_refresh == 0.0


def test_estimate_scales_with_query_count_and_concurrency():
    result = estimate_cost(cache_misses=100, stale_count=20, max_concurrency=10, profile=PROFILE)

    assert result.queries_without_refresh == 100
    assert result.queries_with_refresh == 120
    assert result.cost_usd_without_refresh == (PROFILE.cost_per_query_usd * 100).quantize(Decimal("0.01"))
    assert result.cost_usd_with_refresh == (PROFILE.cost_per_query_usd * 120).quantize(Decimal("0.01"))
    assert result.seconds_without_refresh == (100 / 10) * PROFILE.seconds_per_query
    assert result.seconds_with_refresh == (120 / 10) * PROFILE.seconds_per_query


def test_estimate_with_refresh_is_never_cheaper_than_without():
    result = estimate_cost(cache_misses=50, stale_count=5, max_concurrency=5, profile=PROFILE)

    assert result.queries_with_refresh >= result.queries_without_refresh
    assert result.cost_usd_with_refresh >= result.cost_usd_without_refresh
    assert result.seconds_with_refresh >= result.seconds_without_refresh


def test_estimate_uses_the_given_profiles_own_cost_and_timing():
    # A near-zero-cost profile (e.g. Groq's free tier) must actually change
    # the numbers, proving estimate_cost reads the passed profile and not a
    # module-level constant left over from the old signature.
    free_profile = ProviderProfile(cost_per_query_usd=Decimal("0.000"), seconds_per_query=4.0)

    result = estimate_cost(cache_misses=10, stale_count=0, max_concurrency=5, profile=free_profile)

    assert result.cost_usd_without_refresh == Decimal("0.00")
    assert result.seconds_without_refresh == (10 / 5) * 4.0
