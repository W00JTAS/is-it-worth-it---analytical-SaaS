from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


def round_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round_pct(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class CostConfig:
    commission_pct: Decimal
    shipping_cost: Decimal
    vat_pct: Decimal
    returns_pct: Decimal


@dataclass(frozen=True)
class MarginResult:
    scenario_pct: Decimal
    sale_price: Decimal
    net_revenue: Decimal
    total_costs: Decimal
    margin: Decimal
    margin_pct: Decimal
