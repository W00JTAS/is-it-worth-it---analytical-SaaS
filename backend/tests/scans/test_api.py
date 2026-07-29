import io
import logging
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.cache.sqlite_cache import PriceCache
from app.providers.base import OfferResult
from app.scans.api import get_cache, get_provider, get_store, router
from app.scans.store import ScanStore

CSV_BYTES = (
    "nazwa;cena;ean;kategoria\n"
    "Produkt A;10,00;5901234123457;Elektronika\n"
).encode("utf-8")


class _FakeProvider:
    name = "perplexity"

    def find_cheapest(self, product, market, max_delivery_days):
        return OfferResult(
            price=Decimal("15.00"), currency="PLN",
            seller="Shop", source_url="https://example.com/x", delivery_days=2,
            confidence=0.9, citations=(), raw_response="{}",
        )


class _BuggyProvider:
    """Simulates a genuine bug in the provider (NOT ProviderUnavailable) so we
    can verify a crash inside run_scan's background task doesn't vanish
    silently and doesn't leave the scan stuck in RUNNING forever."""

    name = "perplexity"

    def find_cheapest(self, product, market, max_delivery_days):
        raise RuntimeError("boom: simulated genuine bug, not a transient failure")


def _make_app(tmp_path, provider=None):
    app = FastAPI()
    app.include_router(router)
    store = ScanStore(tmp_path / "app.sqlite3")
    cache = PriceCache(tmp_path / "app.sqlite3")
    provider = provider or _FakeProvider()
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_cache] = lambda: cache
    app.dependency_overrides[get_provider] = lambda: provider
    return app, store, cache


def test_post_scans_creates_an_estimated_scan_without_starting_it(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "full"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "estimated"
    assert body["total_products"] == 1
    assert "estimate" in body
    assert store.get_scan(body["scan_id"]).status.value == "estimated"


def test_post_scans_response_includes_overlapping_and_stale_counts(tmp_path):
    # Task 6's StalenessReport (overlapping_count / stale_external_ids) must
    # reach the API response, not just be discarded after computing the cost
    # estimate. Pre-seed the cache so one product overlaps an existing entry.
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)
    cache.set(
        "5901234123457", "PL", "perplexity", 5,
        OfferResult(
            price=Decimal("15.00"), currency="PLN", seller="Shop",
            source_url="https://example.com/x", delivery_days=2,
            confidence=0.9, citations=(), raw_response="{}",
        ),
    )

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "full"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["overlapping_count"] == 1
    assert body["stale_count"] == 0


def test_get_scans_returns_404_for_unknown_id(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.get("/scans/does-not-exist")

    assert response.status_code == 404


def test_start_scan_runs_it_to_completion(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)
    scan_id = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "full"},
    ).json()["scan_id"]

    response = client.post(f"/scans/{scan_id}/start", json={"force_refresh_stale": False})

    assert response.status_code == 200
    final = client.get(f"/scans/{scan_id}").json()
    assert final["status"] == "done"
    assert final["completed_products"] == 1


def test_start_scan_returns_404_for_unknown_id(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post("/scans/does-not-exist/start", json={"force_refresh_stale": False})

    assert response.status_code == 404


# --- Carried-forward fix 1 (Task 8 review): reject invalid scope_type ------


def test_post_scans_rejects_invalid_scope_type(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "bogus"},
    )

    assert response.status_code == 400


def test_post_scans_accepts_sample_scope_type(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "sample", "sample_per_category": "1"},
    )

    assert response.status_code == 200


# --- Carried-forward fix 2 (Task 9 review): background task crash is not --
# --- silently invisible and doesn't leave the scan stuck forever ----------


def test_start_scan_marks_scan_failed_and_logs_when_run_scan_crashes_unexpectedly(
    tmp_path, caplog
):
    app, store, cache = _make_app(tmp_path, provider=_BuggyProvider())
    client = TestClient(app)
    scan_id = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "full"},
    ).json()["scan_id"]

    with caplog.at_level(logging.ERROR):
        response = client.post(f"/scans/{scan_id}/start", json={"force_refresh_stale": False})

    assert response.status_code == 200

    final = client.get(f"/scans/{scan_id}").json()
    # The genuine bug must not leave the scan stuck at "running"/"estimated"
    # forever with no trace -- it should be finalized (and, since the product
    # never completed, that finalization lands on "failed").
    assert final["status"] not in ("estimated", "running")
    assert final["status"] == "failed"

    # And the crash must be logged loudly, not swallowed silently.
    assert any("run_scan" in record.message or "boom" in record.message for record in caplog.records)
