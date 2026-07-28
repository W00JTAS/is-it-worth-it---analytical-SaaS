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


def calculate_margin(
    wholesale_price: Decimal,
    market_price: Decimal,
    cost_config: CostConfig,
    scenario_pct: Decimal,
) -> MarginResult:
    sale_price = market_price * (Decimal("1") + scenario_pct)
    net_revenue = sale_price / (Decimal("1") + cost_config.vat_pct)
    commission_amount = sale_price * cost_config.commission_pct
    returns_amount = sale_price * cost_config.returns_pct
    total_costs = wholesale_price + cost_config.shipping_cost + commission_amount + returns_amount
    margin = net_revenue - total_costs
    margin_pct = margin / sale_price

    return MarginResult(
        scenario_pct=scenario_pct,
        sale_price=round_money(sale_price),
        net_revenue=round_money(net_revenue),
        total_costs=round_money(total_costs),
        margin=round_money(margin),
        margin_pct=round_pct(margin_pct),
    )
