from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.product import Product
from app.providers.base import OfferResult
from app.reports.api import router
from app.scans.api import get_store
from app.scans.estimate import estimate_cost
from app.scans.store import ScanStore

COST_PARAMS = {
    "commission_pct": "0.10", "shipping_cost": "15.00",
    "vat_pct": "0.23", "returns_pct": "0.02",
}


def _make_app(tmp_path):
    app = FastAPI()
    app.include_router(router)
    store = ScanStore(tmp_path / "app.sqlite3")
    app.dependency_overrides[get_store] = lambda: store
    return app, store


def _make_product(**overrides) -> Product:
    defaults = dict(
        tenant_id="t1", source="csv", external_id="1", variant_id=None,
        name="Test Product", ean="5901234123457",
        wholesale_price=Decimal("40.00"), currency="PLN", category="Elektronika",
    )
    defaults.update(overrides)
    return Product(**defaults)


def _seed_done_scan(store: ScanStore, *, offer_price=Decimal("100.00")) -> str:
    estimate = estimate_cost(cache_misses=1, stale_count=0, max_concurrency=5)
    scan_id = store.create_scan(
        scope_type="full", sample_per_category=None, market="PL", max_delivery_days=5,
        max_concurrency=5, staleness_threshold_days=14,
        products=[_make_product()], stale_eans=(), estimate=estimate,
        overlapping_count=0, stale_count=0,
    )
    record = store.list_pending(scan_id)[0]
    offer = OfferResult(
        price=offer_price, currency="PLN", seller="Shop",
        source_url="https://example.com/x", delivery_days=2,
        confidence=0.9, citations=(), raw_response="{}",
    )
    store.mark_done(record.id, offer)
    store.finalize_scan(scan_id)
    return scan_id


def test_report_summary_returns_computed_aggregates(tmp_path):
    app, store = _make_app(tmp_path)
    client = TestClient(app)
    scan_id = _seed_done_scan(store)

    response = client.get(f"/scans/{scan_id}/report/summary", params=COST_PARAMS)

    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["total"] == 1
    assert body["counts"]["computable"] == 1
    assert len(body["scenario_matrix"]) == 4
    assert body["category_table"][0]["category"] == "Elektronika"
    store.close()


def test_report_summary_404_for_unknown_scan(tmp_path):
    app, store = _make_app(tmp_path)
    client = TestClient(app)

    response = client.get("/scans/does-not-exist/report/summary", params=COST_PARAMS)

    assert response.status_code == 404
    store.close()


def test_report_summary_400_when_scan_not_terminal(tmp_path):
    app, store = _make_app(tmp_path)
    client = TestClient(app)
    estimate = estimate_cost(cache_misses=1, stale_count=0, max_concurrency=5)
    scan_id = store.create_scan(
        scope_type="full", sample_per_category=None, market="PL", max_delivery_days=5,
        max_concurrency=5, staleness_threshold_days=14,
        products=[_make_product()], stale_eans=(), estimate=estimate,
        overlapping_count=0, stale_count=0,
    )

    response = client.get(f"/scans/{scan_id}/report/summary", params=COST_PARAMS)

    assert response.status_code == 400
    store.close()


def test_report_summary_400_for_negative_cost_value(tmp_path):
    app, store = _make_app(tmp_path)
    client = TestClient(app)
    scan_id = _seed_done_scan(store)

    response = client.get(
        f"/scans/{scan_id}/report/summary",
        params={**COST_PARAMS, "shipping_cost": "-5"},
    )

    assert response.status_code == 400
    store.close()


def test_report_products_returns_paginated_rows_with_offer_and_margin_matrix(tmp_path):
    app, store = _make_app(tmp_path)
    client = TestClient(app)
    scan_id = _seed_done_scan(store)

    response = client.get(
        f"/scans/{scan_id}/report/products",
        params={**COST_PARAMS, "page": 1, "page_size": 10},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    row = body["rows"][0]
    assert row["computable"] is True
    assert len(row["margin_matrix"]) == 4
    assert row["offer"]["seller"] == "Shop"
    assert isinstance(row["id"], int)
    store.close()


def test_report_products_400_for_invalid_sort(tmp_path):
    app, store = _make_app(tmp_path)
    client = TestClient(app)
    scan_id = _seed_done_scan(store)

    response = client.get(
        f"/scans/{scan_id}/report/products",
        params={**COST_PARAMS, "sort": "bogus"},
    )

    assert response.status_code == 400
    store.close()


def test_report_products_filters_by_status(tmp_path):
    app, store = _make_app(tmp_path)
    client = TestClient(app)
    scan_id = _seed_done_scan(store)

    response = client.get(
        f"/scans/{scan_id}/report/products",
        params={**COST_PARAMS, "status": "no_offer"},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 0
    store.close()
