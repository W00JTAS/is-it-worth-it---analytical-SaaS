from decimal import Decimal

from app.models.product import Product
from app.providers.base import OfferResult
from app.scans.estimate import estimate_cost
from app.scans.models import ProductStatus, ScanStatus
from app.scans.store import ScanStore


def _make_product(**overrides) -> Product:
    defaults = dict(
        tenant_id="t1", source="csv", external_id="1", variant_id=None,
        name="Test Product", ean="5901234123457",
        wholesale_price=Decimal("60.00"), currency="PLN", category="Test",
    )
    defaults.update(overrides)
    return Product(**defaults)


def _make_offer(**overrides) -> OfferResult:
    defaults = dict(
        price=Decimal("89.99"), currency="PLN", seller="Example Shop",
        source_url="https://example.com/product", delivery_days=2,
        confidence=0.85, citations=("https://example.com/product",),
        raw_response="{}",
    )
    defaults.update(overrides)
    return OfferResult(**defaults)


def test_create_scan_persists_scan_and_products(tmp_path):
    store = ScanStore(tmp_path / "app.sqlite3")
    products = [_make_product(external_id="1"), _make_product(external_id="2", ean=None)]
    estimate = estimate_cost(cache_misses=2, stale_count=0, max_concurrency=5)

    scan_id = store.create_scan(
        scope_type="full", sample_per_category=None, market="PL", max_delivery_days=5,
        max_concurrency=5, staleness_threshold_days=14,
        products=products, stale_external_ids=(), estimate=estimate,
        overlapping_count=0, stale_count=0,
    )

    scan = store.get_scan(scan_id)
    assert scan is not None
    assert scan.status == ScanStatus.ESTIMATED
    assert scan.total_products == 2
    assert scan.completed_products == 0
    assert scan.estimate.queries_without_refresh == 2

    pending = store.list_pending(scan_id)
    assert len(pending) == 2
    assert {p.product.external_id for p in pending} == {"1", "2"}
    assert all(p.status == ProductStatus.PENDING for p in pending)
    store.close()


def test_stale_products_are_flagged_on_creation(tmp_path):
    store = ScanStore(tmp_path / "app.sqlite3")
    products = [_make_product(external_id="1"), _make_product(external_id="2")]
    estimate = estimate_cost(cache_misses=1, stale_count=1, max_concurrency=5)

    scan_id = store.create_scan(
        scope_type="full", sample_per_category=None, market="PL", max_delivery_days=5,
        max_concurrency=5, staleness_threshold_days=14,
        products=products, stale_external_ids=("2",), estimate=estimate,
        overlapping_count=1, stale_count=1,
    )

    pending = {p.product.external_id: p for p in store.list_pending(scan_id)}
    assert pending["1"].was_stale is False
    assert pending["2"].was_stale is True

    # overlapping_count/stale_count must round-trip through get_scan, not just
    # be accepted and discarded (this is the whole point of Task 6's staleness
    # analysis reaching API consumers).
    scan = store.get_scan(scan_id)
    assert scan.overlapping_count == 1
    assert scan.stale_count == 1
    store.close()


def test_get_scan_returns_none_for_unknown_id(tmp_path):
    store = ScanStore(tmp_path / "app.sqlite3")
    assert store.get_scan("does-not-exist") is None
    store.close()


def test_start_scan_sets_status_running(tmp_path):
    store = ScanStore(tmp_path / "app.sqlite3")
    estimate = estimate_cost(cache_misses=1, stale_count=0, max_concurrency=5)
    scan_id = store.create_scan(
        scope_type="full", sample_per_category=None, market="PL", max_delivery_days=5,
        max_concurrency=5, staleness_threshold_days=14,
        products=[_make_product()], stale_external_ids=(), estimate=estimate,
        overlapping_count=0, stale_count=0,
    )

    store.start_scan(scan_id)

    assert store.get_scan(scan_id).status == ScanStatus.RUNNING
    store.close()


def test_mark_done_updates_status_offer_and_progress_count(tmp_path):
    store = ScanStore(tmp_path / "app.sqlite3")
    estimate = estimate_cost(cache_misses=1, stale_count=0, max_concurrency=5)
    scan_id = store.create_scan(
        scope_type="full", sample_per_category=None, market="PL", max_delivery_days=5,
        max_concurrency=5, staleness_threshold_days=14,
        products=[_make_product()], stale_external_ids=(), estimate=estimate,
        overlapping_count=0, stale_count=0,
    )
    record = store.list_pending(scan_id)[0]
    offer = _make_offer()

    store.mark_done(record.id, offer)

    assert store.list_pending(scan_id) == []
    assert store.get_scan(scan_id).completed_products == 1
    store.close()


def test_mark_skipped_updates_status_and_progress_without_counting_as_pending(tmp_path):
    store = ScanStore(tmp_path / "app.sqlite3")
    estimate = estimate_cost(cache_misses=0, stale_count=1, max_concurrency=5)
    scan_id = store.create_scan(
        scope_type="full", sample_per_category=None, market="PL", max_delivery_days=5,
        max_concurrency=5, staleness_threshold_days=14,
        products=[_make_product()], stale_external_ids=("1",), estimate=estimate,
        overlapping_count=0, stale_count=0,
    )
    record = store.list_pending(scan_id)[0]
    offer = _make_offer()

    store.mark_skipped(record.id, offer)

    assert store.list_pending(scan_id) == []
    assert store.get_scan(scan_id).completed_products == 1
    store.close()


def test_finalize_scan_is_done_when_nothing_pending(tmp_path):
    store = ScanStore(tmp_path / "app.sqlite3")
    estimate = estimate_cost(cache_misses=1, stale_count=0, max_concurrency=5)
    scan_id = store.create_scan(
        scope_type="full", sample_per_category=None, market="PL", max_delivery_days=5,
        max_concurrency=5, staleness_threshold_days=14,
        products=[_make_product()], stale_external_ids=(), estimate=estimate,
        overlapping_count=0, stale_count=0,
    )
    store.mark_done(store.list_pending(scan_id)[0].id, _make_offer())

    store.finalize_scan(scan_id)

    assert store.get_scan(scan_id).status == ScanStatus.DONE
    store.close()


def test_finalize_scan_is_failed_when_products_still_pending(tmp_path):
    store = ScanStore(tmp_path / "app.sqlite3")
    estimate = estimate_cost(cache_misses=2, stale_count=0, max_concurrency=5)
    scan_id = store.create_scan(
        scope_type="full", sample_per_category=None, market="PL", max_delivery_days=5,
        max_concurrency=5, staleness_threshold_days=14,
        products=[_make_product(external_id="1"), _make_product(external_id="2")],
        stale_external_ids=(), estimate=estimate,
        overlapping_count=0, stale_count=0,
    )
    store.mark_done(store.list_pending(scan_id)[0].id, _make_offer())
    # One product ("2") is still pending.

    store.finalize_scan(scan_id)

    assert store.get_scan(scan_id).status == ScanStatus.FAILED
    store.close()
