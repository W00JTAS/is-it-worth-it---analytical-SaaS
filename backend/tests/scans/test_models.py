from decimal import Decimal

from app.models.product import Product
from app.providers.base import OfferResult
from app.scans.models import (
    CostEstimate,
    ProductStatus,
    Scan,
    ScanProductRecord,
    ScanStatus,
    StalenessReport,
)


def _make_product(**overrides) -> Product:
    defaults = dict(
        tenant_id="t1", source="csv", external_id="1", variant_id=None,
        name="Test Product", ean="5901234123457",
        wholesale_price=Decimal("60.00"), currency="PLN", category="Test",
    )
    defaults.update(overrides)
    return Product(**defaults)


def _make_estimate(**overrides) -> CostEstimate:
    defaults = dict(
        queries_without_refresh=10, queries_with_refresh=12,
        cost_usd_without_refresh=Decimal("0.10"), cost_usd_with_refresh=Decimal("0.12"),
        seconds_without_refresh=20.0, seconds_with_refresh=24.0,
    )
    defaults.update(overrides)
    return CostEstimate(**defaults)


def test_scan_status_values():
    assert ScanStatus.ESTIMATED.value == "estimated"
    assert ScanStatus.RUNNING.value == "running"
    assert ScanStatus.DONE.value == "done"
    assert ScanStatus.FAILED.value == "failed"


def test_product_status_values():
    assert ProductStatus.PENDING.value == "pending"
    assert ProductStatus.DONE.value == "done"
    assert ProductStatus.SKIPPED.value == "skipped"


def test_scan_holds_all_fields():
    scan = Scan(
        id="scan-1", status=ScanStatus.ESTIMATED, scope_type="sample",
        sample_per_category=50, market="PL", max_delivery_days=5,
        max_concurrency=5, staleness_threshold_days=14,
        total_products=100, completed_products=0,
        estimate=_make_estimate(), overlapping_count=5, stale_count=2,
        created_at=1700000000.0,
    )
    assert scan.id == "scan-1"
    assert scan.status == ScanStatus.ESTIMATED
    assert scan.scope_type == "sample"
    assert scan.sample_per_category == 50
    assert scan.estimate.queries_without_refresh == 10
    assert scan.overlapping_count == 5
    assert scan.stale_count == 2


def test_scan_product_record_holds_all_fields():
    product = _make_product()
    record = ScanProductRecord(
        id=1, scan_id="scan-1", product=product,
        status=ProductStatus.PENDING, was_stale=False, offer=None,
    )
    assert record.id == 1
    assert record.scan_id == "scan-1"
    assert record.product == product
    assert record.status == ProductStatus.PENDING
    assert record.was_stale is False
    assert record.offer is None


def test_staleness_report_holds_fields():
    report = StalenessReport(overlapping_count=3, stale_external_ids=("1", "2"))
    assert report.overlapping_count == 3
    assert report.stale_external_ids == ("1", "2")
