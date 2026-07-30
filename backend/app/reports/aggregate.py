from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from app.pricing.margin import CostConfig, SCENARIO_ADJUSTMENTS
from app.reports.evaluate import ExclusionReason, evaluate_record
from app.scans.models import ScanProductRecord

_REFERENCE_SCENARIO_INDEX = SCENARIO_ADJUSTMENTS.index(Decimal("0.00"))


@dataclass(frozen=True)
class ReportCounts:
    total: int
    computable: int
    not_checked: int
    no_offer: int
    currency_mismatch: int
    anomaly: int


@dataclass(frozen=True)
class CategoryRow:
    category: str
    computable_count: int
    excluded_count: int
    avg_margin_pct: Decimal | None


@dataclass(frozen=True)
class ScenarioRow:
    scenario_pct: Decimal
    avg_margin_pct: Decimal | None
    profitable_count: int


@dataclass(frozen=True)
class ReportSummary:
    counts: ReportCounts
    category_table: tuple[CategoryRow, ...]
    scenario_matrix: tuple[ScenarioRow, ...]


def build_summary(records: Iterable[ScanProductRecord], cost_config: CostConfig) -> ReportSummary:
    total = not_checked = no_offer = currency_mismatch = anomaly = computable = 0
    category_computable: dict[str, int] = defaultdict(int)
    category_excluded: dict[str, int] = defaultdict(int)
    category_margin_sum: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    scenario_margin_sum = [Decimal("0") for _ in SCENARIO_ADJUSTMENTS]
    scenario_profitable = [0 for _ in SCENARIO_ADJUSTMENTS]

    for record in records:
        total += 1
        evaluation = evaluate_record(record, cost_config)
        category = record.product.category

        if not evaluation.computable:
            category_excluded[category] += 1
            if evaluation.exclusion_reason == ExclusionReason.NOT_CHECKED:
                not_checked += 1
            elif evaluation.exclusion_reason == ExclusionReason.NO_OFFER:
                no_offer += 1
            elif evaluation.exclusion_reason == ExclusionReason.CURRENCY_MISMATCH:
                currency_mismatch += 1
            elif evaluation.exclusion_reason == ExclusionReason.ANOMALY:
                anomaly += 1
            continue

        computable += 1
        category_computable[category] += 1
        category_margin_sum[category] += evaluation.margin_matrix[_REFERENCE_SCENARIO_INDEX].margin_pct
        for i, result in enumerate(evaluation.margin_matrix):
            scenario_margin_sum[i] += result.margin_pct
            if result.margin > 0:
                scenario_profitable[i] += 1

    all_categories = sorted(set(category_computable) | set(category_excluded))
    category_table = tuple(
        CategoryRow(
            category=category,
            computable_count=category_computable.get(category, 0),
            excluded_count=category_excluded.get(category, 0),
            avg_margin_pct=(
                category_margin_sum[category] / category_computable[category]
                if category_computable.get(category)
                else None
            ),
        )
        for category in all_categories
    )

    scenario_matrix = tuple(
        ScenarioRow(
            scenario_pct=scenario_pct,
            avg_margin_pct=(scenario_margin_sum[i] / computable if computable else None),
            profitable_count=scenario_profitable[i],
        )
        for i, scenario_pct in enumerate(SCENARIO_ADJUSTMENTS)
    )

    return ReportSummary(
        counts=ReportCounts(
            total=total, computable=computable, not_checked=not_checked,
            no_offer=no_offer, currency_mismatch=currency_mismatch, anomaly=anomaly,
        ),
        category_table=category_table,
        scenario_matrix=scenario_matrix,
    )
