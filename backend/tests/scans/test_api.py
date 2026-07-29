import asyncio
import io
import logging
from decimal import Decimal

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.background import BackgroundTasks

import app.scans.api as api_module
from app.cache.sqlite_cache import PriceCache
from app.providers.base import OfferResult
from app.scans.api import (
    StartScanRequest,
    _scans_in_flight,
    get_cache,
    get_provider,
    get_store,
    router,
    start_scan,
)
from app.scans.store import ScanStore

CSV_BYTES = (
    "nazwa;cena;ean;kategoria\n"
    "Produkt A;10,00;5901234123457;Elektronika\n"
).encode("utf-8")


class _FakeProvider:
    name = "perplexity"

    def __init__(self):
        self.call_count = 0

    def find_cheapest(self, product, market, max_delivery_days):
        self.call_count += 1
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
    assert body["warnings"] == []
    assert store.get_scan(body["scan_id"]).status.value == "estimated"


def test_post_scans_response_includes_overlapping_and_stale_counts(tmp_path):
    # Task 6's StalenessReport (overlapping_count / stale_eans) must
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


# --- Critical 1 (final whole-branch review): reject a duplicate start ------


def test_second_start_scan_call_is_rejected_while_first_is_in_flight(tmp_path):
    # TestClient runs background tasks synchronously after the response, so
    # two sequential client.post() calls can't naturally reproduce the race:
    # by the time the second request is made, the first's background task has
    # already finished. Instead, call the `start_scan` endpoint function
    # directly and control background-task execution ourselves, so we can
    # dispatch the first task, then attempt (and reject) a second dispatch
    # *before* the first has actually run.
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)
    provider = _FakeProvider()
    app.dependency_overrides[get_provider] = lambda: provider
    scan_id = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "full"},
    ).json()["scan_id"]

    async def scenario():
        body = StartScanRequest(force_refresh_stale=False)
        bg1 = BackgroundTasks()
        result1 = await start_scan(scan_id, body, bg1, store, cache, provider)
        assert result1 == {"status": "running"}
        assert scan_id in _scans_in_flight

        bg2 = BackgroundTasks()
        with pytest.raises(HTTPException) as exc_info:
            await start_scan(scan_id, body, bg2, store, cache, provider)
        assert exc_info.value.status_code == 409

        # Now actually run the (only) dispatched background task.
        await bg1()
        assert scan_id not in _scans_in_flight

    asyncio.run(scenario())

    final = store.get_scan(scan_id)
    assert final.status.value == "done"
    assert provider.call_count == 1  # one product, one call -- not doubled


# --- Important 2 (final whole-branch review): reject bad scan input -------


def test_post_scans_rejects_zero_max_concurrency(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "full", "max_concurrency": "0"},
    )

    assert response.status_code == 400


def test_post_scans_rejects_negative_max_concurrency(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "full", "max_concurrency": "-1"},
    )

    assert response.status_code == 400


def test_post_scans_rejects_zero_max_delivery_days(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "full", "max_delivery_days": "0"},
    )

    assert response.status_code == 400


def test_post_scans_rejects_negative_staleness_threshold_days(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "full", "staleness_threshold_days": "-1"},
    )

    assert response.status_code == 400


def test_post_scans_rejects_sample_scope_without_sample_per_category(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "sample"},
    )

    assert response.status_code == 400


def test_post_scans_rejects_sample_scope_with_zero_sample_per_category(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "sample", "sample_per_category": "0"},
    )

    assert response.status_code == 400


def test_post_scans_rejects_empty_csv_file(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(b""), "text/csv")},
        data={"scope_type": "full"},
    )

    assert response.status_code == 400


def test_post_scans_rejects_csv_with_unrecognizable_header(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)
    bad_csv = "foo;bar;baz;qux\nx;y;z;w\n".encode("utf-8")

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(bad_csv), "text/csv")},
        data={"scope_type": "full"},
    )

    assert response.status_code == 400


# --- Important 3 (final whole-branch review): CSV parse warnings surface --


def test_post_scans_response_includes_csv_parse_warnings(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)
    csv_bytes = (
        "nazwa;cena;ean;kategoria\n"
        "Produkt A;10,00;5901234123457;Elektronika\n"
        "Produkt B;abc;5900000000107;Dom\n"  # invalid price -> dropped, warned
    ).encode("utf-8")

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(csv_bytes), "text/csv")},
        data={"scope_type": "full"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_products"] == 1
    assert len(body["warnings"]) == 1
    assert "invalid price" in body["warnings"][0]


# --- Minor fix (final whole-branch review): bound the SSE stream for a ----
# --- scan that's never started ---------------------------------------------


def test_events_stream_stops_after_bounded_estimated_ticks(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "SSE_MAX_ESTIMATED_TICKS", 2)
    monkeypatch.setattr(api_module, "SSE_POLL_INTERVAL_SECONDS", 0.01)
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)
    scan_id = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "full"},
    ).json()["scan_id"]
    # Deliberately never started -- stays "estimated" forever.

    response = client.get(f"/scans/{scan_id}/events")

    assert response.status_code == 200
    assert '"status": "timeout"' in response.text
