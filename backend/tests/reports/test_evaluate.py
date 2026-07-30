from decimal import Decimal

from app.models.product import Product
from app.pricing.margin import CostConfig
from app.providers.anomaly import AnomalyFlag
from app.providers.base import OfferResult
from app.reports.evaluate import ExclusionReason, evaluate_record
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
        confidence=0.9, citations=("https://example.com/x",), raw_response="{}",
    )
    defaults.update(overrides)
    return OfferResult(**defaults)


def _make_record(*, status=ProductStatus.DONE, offer=None, **product_overrides) -> ScanProductRecord:
    return ScanProductRecord(
        id=1, scan_id="scan-1", product=_make_product(**product_overrides),
        status=status, was_stale=False, offer=offer,
    )


def test_computable_product_gets_full_four_scenario_margin_matrix():
    record = _make_record(offer=_make_offer())

    evaluation = evaluate_record(record, COST_CONFIG)

    assert evaluation.computable is True
    assert evaluation.exclusion_reason is None
    assert evaluation.anomaly_flag is None
    assert evaluation.margin_matrix is not None
    assert len(evaluation.margin_matrix) == 4
    assert evaluation.margin_matrix[2].scenario_pct == Decimal("0.00")


def test_not_checked_when_status_is_pending():
    record = _make_record(status=ProductStatus.PENDING, offer=None)

    evaluation = evaluate_record(record, COST_CONFIG)

    assert evaluation.computable is False
    assert evaluation.exclusion_reason == ExclusionReason.NOT_CHECKED
    assert evaluation.margin_matrix is None


def test_no_offer_when_done_but_offer_is_none():
    record = _make_record(status=ProductStatus.DONE, offer=None)

    evaluation = evaluate_record(record, COST_CONFIG)

    assert evaluation.exclusion_reason == ExclusionReason.NO_OFFER


def test_currency_mismatch_when_offer_currency_differs_from_product_currency():
    record = _make_record(offer=_make_offer(currency="EUR"))

    evaluation = evaluate_record(record, COST_CONFIG)

    assert evaluation.exclusion_reason == ExclusionReason.CURRENCY_MISMATCH
    assert evaluation.margin_matrix is None


def test_anomaly_flag_set_for_below_wholesale_offer():
    record = _make_record(wholesale_price=Decimal("200.00"), offer=_make_offer(price=Decimal("100.00")))

    evaluation = evaluate_record(record, COST_CONFIG)

    assert evaluation.exclusion_reason == ExclusionReason.ANOMALY
    assert evaluation.anomaly_flag == AnomalyFlag.BELOW_WHOLESALE


def test_anomaly_flag_set_for_low_confidence_offer():
    record = _make_record(offer=_make_offer(confidence=0.2))

    evaluation = evaluate_record(record, COST_CONFIG)

    assert evaluation.exclusion_reason == ExclusionReason.ANOMALY
    assert evaluation.anomaly_flag == AnomalyFlag.LOW_CONFIDENCE
