from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.pricing.margin import CostConfig, MarginResult, calculate_margin_matrix
from app.providers.anomaly import AnomalyFlag, detect_anomaly
from app.scans.models import ProductStatus, ScanProductRecord


class ExclusionReason(str, Enum):
    NOT_CHECKED = "not_checked"
    NO_OFFER = "no_offer"
    CURRENCY_MISMATCH = "currency_mismatch"
    ANOMALY = "anomaly"


@dataclass(frozen=True)
class ProductEvaluation:
    record: ScanProductRecord
    computable: bool
    exclusion_reason: ExclusionReason | None
    anomaly_flag: AnomalyFlag | None
    margin_matrix: tuple[MarginResult, ...] | None


def _excluded(record: ScanProductRecord, reason: ExclusionReason, anomaly_flag: AnomalyFlag | None = None) -> ProductEvaluation:
    return ProductEvaluation(
        record=record, computable=False, exclusion_reason=reason,
        anomaly_flag=anomaly_flag, margin_matrix=None,
    )


def evaluate_record(record: ScanProductRecord, cost_config: CostConfig) -> ProductEvaluation:
    if record.status != ProductStatus.DONE:
        return _excluded(record, ExclusionReason.NOT_CHECKED)
    if record.offer is None:
        return _excluded(record, ExclusionReason.NO_OFFER)
    if record.offer.currency != record.product.currency:
        return _excluded(record, ExclusionReason.CURRENCY_MISMATCH)

    anomaly = detect_anomaly(record.offer, record.product.wholesale_price)
    if anomaly is not None:
        return _excluded(record, ExclusionReason.ANOMALY, anomaly_flag=anomaly)

    matrix = tuple(
        calculate_margin_matrix(record.product.wholesale_price, record.offer.price, cost_config)
    )
    return ProductEvaluation(
        record=record, computable=True, exclusion_reason=None,
        anomaly_flag=None, margin_matrix=matrix,
    )
