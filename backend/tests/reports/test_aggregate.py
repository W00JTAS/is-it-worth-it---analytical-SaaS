from decimal import Decimal

from app.models.product import Product
from app.pricing.margin import CostConfig, SCENARIO_ADJUSTMENTS, calculate_margin
from app.providers.base import OfferResult
from app.reports.aggregate import build_summary
from app.scans.models import ProductStatus, ScanProductRecord

COST_CONFIG = CostConfig(
    commission_pct=Decimal("0.10"),
    shipping_cost=Decimal("15.00"),
    vat_pct=Decimal("0.23"),
    returns_pct=Decimal("0.02"),
)


def _make_product(**overrides) -> Product:
    defaults = dict(
        tenant_id="t1", source="csv", external_id="1", variant_id=None,
        name="Test Product", ean="5901234123457",
        wholesale_price=Decimal("40.00"), currency="PLN", category="Elektronika",
    )
    defaults.update(overrides)
    return Product(**defaults)


def _make_offer(**overrides) -> OfferResult:
    defaults = dict(
        price=Decimal("100.00"), currency="PLN", seller="Shop",
        source_url="https://example.com/x", delivery_days=2,
        confidence=0.9, citations=(), raw_response="{}",
    )
    defaults.update(overrides)
    return OfferResult(**defaults)


def _make_record(record_id, *, status=ProductStatus.DONE, offer=None, **product_overrides) -> ScanProductRecord:
    return ScanProductRecord(
        id=record_id, scan_id="scan-1", product=_make_product(**product_overrides),
        status=status, was_stale=False, offer=offer,
    )


def test_build_summary_counts_and_buckets_by_exclusion_reason():
    records = [
        _make_record(1, offer=_make_offer(price=Decimal("100.00")), wholesale_price=Decimal("40.00"), category="Elektronika"),
        _make_record(2, offer=_make_offer(price=Decimal("100.00")), wholesale_price=Decimal("60.00"), category="Elektronika"),
        _make_record(3, status=ProductStatus.DONE, offer=None, category="Elektronika"),
        _make_record(4, offer=_make_offer(confidence=0.1), category="Dom"),
        _make_record(5, offer=_make_offer(currency="EUR"), category="Dom"),
        _make_record(6, status=ProductStatus.PENDING, offer=None, category="Dom"),
    ]

    summary = build_summary(records, COST_CONFIG)

    assert summary.counts.total == 6
    assert summary.counts.computable == 2
    assert summary.counts.no_offer == 1
    assert summary.counts.anomaly == 1
    assert summary.counts.currency_mismatch == 1
    assert summary.counts.not_checked == 1


def test_category_table_averages_only_computable_products_at_reference_scenario():
    records = [
        _make_record(1, offer=_make_offer(price=Decimal("100.00")), wholesale_price=Decimal("40.00"), category="Elektronika"),
        _make_record(2, offer=_make_offer(price=Decimal("100.00")), wholesale_price=Decimal("60.00"), category="Elektronika"),
        _make_record(3, status=ProductStatus.DONE, offer=None, category="Elektronika"),
        _make_record(4, status=ProductStatus.PENDING, offer=None, category="Dom"),
    ]

    summary = build_summary(records, COST_CONFIG)

    by_category = {row.category: row for row in summary.category_table}
    margin_a = calculate_margin(Decimal("40.00"), Decimal("100.00"), COST_CONFIG, Decimal("0.00")).margin_pct
    margin_b = calculate_margin(Decimal("60.00"), Decimal("100.00"), COST_CONFIG, Decimal("0.00")).margin_pct
    assert by_category["Elektronika"].computable_count == 2
    assert by_category["Elektronika"].excluded_count == 1
    assert by_category["Elektronika"].avg_margin_pct == (margin_a + margin_b) / 2
    assert by_category["Dom"].computable_count == 0
    assert by_category["Dom"].excluded_count == 1
    assert by_category["Dom"].avg_margin_pct is None


def test_scenario_matrix_is_global_across_all_computable_products():
    records = [
        _make_record(1, offer=_make_offer(price=Decimal("100.00")), wholesale_price=Decimal("40.00"), category="Elektronika"),
        _make_record(2, offer=_make_offer(price=Decimal("100.00")), wholesale_price=Decimal("60.00"), category="Dom"),
    ]

    summary = build_summary(records, COST_CONFIG)

    assert len(summary.scenario_matrix) == len(SCENARIO_ADJUSTMENTS)
    for row, scenario_pct in zip(summary.scenario_matrix, SCENARIO_ADJUSTMENTS):
        assert row.scenario_pct == scenario_pct
        margin_a = calculate_margin(Decimal("40.00"), Decimal("100.00"), COST_CONFIG, scenario_pct)
        margin_b = calculate_margin(Decimal("60.00"), Decimal("100.00"), COST_CONFIG, scenario_pct)
        assert row.avg_margin_pct == (margin_a.margin_pct + margin_b.margin_pct) / 2
        expected_profitable = sum(1 for m in (margin_a, margin_b) if m.margin > 0)
        assert row.profitable_count == expected_profitable


def test_scenario_matrix_avg_is_none_when_no_computable_products():
    records = [_make_record(1, status=ProductStatus.PENDING, offer=None)]

    summary = build_summary(records, COST_CONFIG)

    assert all(row.avg_margin_pct is None for row in summary.scenario_matrix)
    assert all(row.profitable_count == 0 for row in summary.scenario_matrix)


def test_build_summary_handles_empty_input():
    summary = build_summary([], COST_CONFIG)

    assert summary.counts.total == 0
    assert summary.category_table == ()
    assert all(row.avg_margin_pct is None for row in summary.scenario_matrix)
