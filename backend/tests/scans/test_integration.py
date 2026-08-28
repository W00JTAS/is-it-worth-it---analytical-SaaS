"""End-to-end create -> start -> run coverage.

The design spec's own stated verification criterion is that the pre-scan cost
estimate ("estymacja") must match the actual number of provider queries made
once a scan runs ("faktyczna liczba zapytan"). Every other test exercises
create_scan, run_scan, or the API layer in isolation; this file is the one
place that drives the real API endpoints end-to-end (create -> start) against
a mixed catalog and counts real provider calls, to verify that promise holds.
"""
import io
import time
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.cache.sqlite_cache import PriceCache
from app.providers.base import OfferResult, ProviderProfile
from app.scans.api import get_cache, get_provider, get_store, router
from app.scans.store import ScanStore

MARKET = "PL"
PROVIDER_NAME = "perplexity"
MAX_DELIVERY_DAYS = 5
STALENESS_THRESHOLD_DAYS = 14

# Four products, covering every staleness/cache-overlap combination the
# design spec calls out:
#   A - fresh cache entry (overlapping, not stale)
#   B - stale cache entry (overlapping, stale)
#   C - no prior cache entry (cache miss)
#   D - no EAN at all (always requires a live lookup)
EAN_A = "5901234123457"  # fresh cache entry
EAN_B = "5900000000107"  # stale cache entry
EAN_C = "5900000000206"  # no prior cache entry

CSV_BYTES = (
    "nazwa;cena;ean;kategoria\n"
    f"Produkt A;10,00;{EAN_A};Elektronika\n"
    f"Produkt B;20,00;{EAN_B};Dom\n"
    f"Produkt C;30,00;{EAN_C};Zabawki\n"
    "Produkt D;40,00;;Sport\n"
).encode("utf-8")


def _make_offer(**overrides) -> OfferResult:
    defaults = dict(
        price=Decimal("15.00"), currency="PLN", seller="Example Shop",
        source_url="https://example.com/product", delivery_days=2,
        confidence=0.85, citations=("https://example.com/product",),
        raw_response="{}",
    )
    defaults.update(overrides)
    return OfferResult(**defaults)


class _CountingProvider:
    name = PROVIDER_NAME
    profile = ProviderProfile(cost_per_query_usd=Decimal("0.010"), seconds_per_query=2.5)

    def __init__(self):
        self.call_count = 0

    def find_cheapest(self, product, market, max_delivery_days):
        self.call_count += 1
        return _make_offer()


def _make_app(tmp_path):
    app = FastAPI()
    app.include_router(router)
    store = ScanStore(tmp_path / "app.sqlite3")
    cache = PriceCache(tmp_path / "app.sqlite3")
    provider = _CountingProvider()
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_cache] = lambda: cache
    app.dependency_overrides[get_provider] = lambda: provider
    return app, store, cache, provider


def _seed_cache(cache: PriceCache) -> None:
    # A: fresh -- cached "now", well within the staleness threshold.
    cache.set(EAN_A, MARKET, PROVIDER_NAME, MAX_DELIVERY_DAYS, _make_offer())
    # B: stale -- cached long enough ago to exceed staleness_threshold_days,
    # but still within the cache's own (much longer) TTL, so cache.get()
    # still returns it.
    cache.set(EAN_B, MARKET, PROVIDER_NAME, MAX_DELIVERY_DAYS, _make_offer())
    stale_at = time.time() - ((STALENESS_THRESHOLD_DAYS + 5) * 24 * 3600)
    cache._conn.execute(
        "UPDATE price_cache SET cached_at = ? WHERE ean = ?", (stale_at, EAN_B)
    )
    cache._conn.commit()
    # C: deliberately no prior entry (cache miss).


def _create_and_get_estimate(client: TestClient) -> dict:
    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={
            "scope_type": "full",
            "market": MARKET,
            "max_delivery_days": str(MAX_DELIVERY_DAYS),
            "staleness_threshold_days": str(STALENESS_THRESHOLD_DAYS),
        },
    )
    assert response.status_code == 200
    return response.json()


def test_actual_provider_calls_match_estimate_without_refresh(tmp_path):
    app, store, cache, provider = _make_app(tmp_path)
    client = TestClient(app)
    _seed_cache(cache)

    body = _create_and_get_estimate(client)
    scan_id = body["scan_id"]
    # Sanity check on the scenario itself: C (miss) + D (no EAN) = 2 queries
    # without refresh; + B (stale) = 3 with refresh.
    assert body["estimate"]["queries_without_refresh"] == 2
    assert body["estimate"]["queries_with_refresh"] == 3
    assert body["overlapping_count"] == 2  # A and B both overlap existing cache
    assert body["stale_count"] == 1  # only B is stale

    start_response = client.post(
        f"/scans/{scan_id}/start", json={"force_refresh_stale": False}
    )
    assert start_response.status_code == 200

    final = client.get(f"/scans/{scan_id}").json()
    assert final["status"] == "done"
    assert final["completed_products"] == 4
    # The design spec's own verification criterion: actual provider calls
    # made during the run must equal the pre-scan estimate.
    assert provider.call_count == body["estimate"]["queries_without_refresh"]


def test_actual_provider_calls_match_estimate_with_refresh(tmp_path):
    app, store, cache, provider = _make_app(tmp_path)
    client = TestClient(app)
    _seed_cache(cache)

    body = _create_and_get_estimate(client)
    scan_id = body["scan_id"]
    assert body["estimate"]["queries_without_refresh"] == 2
    assert body["estimate"]["queries_with_refresh"] == 3

    start_response = client.post(
        f"/scans/{scan_id}/start", json={"force_refresh_stale": True}
    )
    assert start_response.status_code == 200

    final = client.get(f"/scans/{scan_id}").json()
    assert final["status"] == "done"
    assert final["completed_products"] == 4
    assert provider.call_count == body["estimate"]["queries_with_refresh"]
