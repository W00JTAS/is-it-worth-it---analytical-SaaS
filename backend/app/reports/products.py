from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from app.pricing.margin import CostConfig, SCENARIO_ADJUSTMENTS
from app.reports.evaluate import ProductEvaluation, evaluate_record
from app.scans.models import ScanProductRecord

_REFERENCE_SCENARIO_INDEX = SCENARIO_ADJUSTMENTS.index(Decimal("0.00"))

VALID_SORTS = ("category", "margin_asc", "margin_desc", "name")
VALID_STATUSES = ("computable", "not_checked", "no_offer", "currency_mismatch", "anomaly")


@dataclass(frozen=True)
class ProductPage:
    rows: tuple[ProductEvaluation, ...]
    total: int
    page: int
    page_size: int


def _status_matches(evaluation: ProductEvaluation, status: str) -> bool:
    if status == "computable":
        return evaluation.computable
    return (
        not evaluation.computable
        and evaluation.exclusion_reason is not None
        and evaluation.exclusion_reason.value == status
    )


def _reference_margin_pct(evaluation: ProductEvaluation) -> Decimal | None:
    if not evaluation.computable or evaluation.margin_matrix is None:
        return None
    return evaluation.margin_matrix[_REFERENCE_SCENARIO_INDEX].margin_pct


def _sort_key(sort: str):
    # Every mode appends e.record.id as the final tiebreaker. Ties on the
    # primary key(s) are common (identical margin from identical wholesale/
    # offer prices, identical product names) and each page is an independent
    # re-fetch-and-re-sort, so without a unique, stable tiebreaker a tied row
    # can land on a different page — or on both, or on neither — between
    # consecutive page requests.
    if sort == "name":
        return lambda e: (e.record.product.name, e.record.id)
    if sort == "margin_asc":
        margin = _reference_margin_pct
        return lambda e: (margin(e) is None, margin(e) or Decimal("0"), e.record.id)
    if sort == "margin_desc":
        margin = _reference_margin_pct
        return lambda e: (margin(e) is None, -(margin(e) or Decimal("0")), e.record.id)
    return lambda e: (e.record.product.category, e.record.product.name, e.record.id)


def list_product_rows(
    records: Iterable[ScanProductRecord],
    cost_config: CostConfig,
    *,
    category: str | None = None,
    status: str | None = None,
    sort: str = "category",
    page: int = 1,
    page_size: int = 50,
) -> ProductPage:
    evaluations = [evaluate_record(record, cost_config) for record in records]
    if category is not None:
        evaluations = [e for e in evaluations if e.record.product.category == category]
    if status is not None:
        evaluations = [e for e in evaluations if _status_matches(e, status)]
    evaluations.sort(key=_sort_key(sort))

    total = len(evaluations)
    start = (page - 1) * page_size
    page_rows = tuple(evaluations[start : start + page_size])
    return ProductPage(rows=page_rows, total=total, page=page, page_size=page_size)
