from decimal import Decimal

from app.models.product import Product
from app.pricing.margin import CostConfig
from app.providers.base import OfferResult
from app.reports.products import list_product_rows
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
        name="B Product", ean="5901234123457",
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
        id=record_id, scan_id="scan-1", product=_make_product(external_id=str(record_id), **product_overrides),
        status=status, was_stale=False, offer=offer,
    )


def test_paginates_results():
    records = [_make_record(i, offer=_make_offer(), name=f"Product {i}") for i in range(1, 6)]

    page1 = list_product_rows(records, COST_CONFIG, page=1, page_size=2)
    page2 = list_product_rows(records, COST_CONFIG, page=2, page_size=2)
    page3 = list_product_rows(records, COST_CONFIG, page=3, page_size=2)

    assert page1.total == 5
    assert len(page1.rows) == 2
    assert len(page2.rows) == 2
    assert len(page3.rows) == 1


def test_filters_by_category():
    records = [
        _make_record(1, offer=_make_offer(), category="Elektronika"),
        _make_record(2, offer=_make_offer(), category="Dom"),
    ]

    page = list_product_rows(records, COST_CONFIG, category="Dom")

    assert page.total == 1
    assert page.rows[0].record.product.category == "Dom"


def test_filters_by_status_computable():
    records = [
        _make_record(1, offer=_make_offer()),
        _make_record(2, status=ProductStatus.DONE, offer=None),
    ]

    page = list_product_rows(records, COST_CONFIG, status="computable")

    assert page.total == 1
    assert page.rows[0].computable is True


def test_filters_by_status_no_offer():
    records = [
        _make_record(1, offer=_make_offer()),
        _make_record(2, status=ProductStatus.DONE, offer=None),
    ]

    page = list_product_rows(records, COST_CONFIG, status="no_offer")

    assert page.total == 1
    assert page.rows[0].exclusion_reason.value == "no_offer"


def test_sorts_by_name():
    records = [
        _make_record(1, offer=_make_offer(), name="Zebra"),
        _make_record(2, offer=_make_offer(), name="Apple"),
    ]

    page = list_product_rows(records, COST_CONFIG, sort="name")

    assert [row.record.product.name for row in page.rows] == ["Apple", "Zebra"]


def test_sorts_by_margin_desc_and_puts_non_computable_rows_last():
    records = [
        _make_record(1, offer=_make_offer(price=Decimal("100.00")), wholesale_price=Decimal("60.00")),  # lower margin
        _make_record(2, offer=_make_offer(price=Decimal("100.00")), wholesale_price=Decimal("40.00")),  # higher margin
        _make_record(3, status=ProductStatus.DONE, offer=None),  # non-computable
    ]

    page = list_product_rows(records, COST_CONFIG, sort="margin_desc")

    assert [row.record.product.external_id for row in page.rows] == ["2", "1", "3"]
