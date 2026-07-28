from decimal import Decimal

from app.pricing.margin import CostConfig, calculate_margin

COST_CONFIG = CostConfig(
    commission_pct=Decimal("0.10"),
    shipping_cost=Decimal("15.00"),
    vat_pct=Decimal("0.23"),
    returns_pct=Decimal("0.02"),
)


def test_unprofitable_at_market_price():
    result = calculate_margin(
        wholesale_price=Decimal("60.00"),
        market_price=Decimal("100.00"),
        cost_config=COST_CONFIG,
        scenario_pct=Decimal("0.00"),
    )
    assert result.sale_price == Decimal("100.00")
    assert result.net_revenue == Decimal("81.30")
    assert result.total_costs == Decimal("87.00")
    assert result.margin == Decimal("-5.70")
    assert result.margin_pct == Decimal("-0.0570")


def test_unprofitable_even_5pct_above_market():
    result = calculate_margin(
        wholesale_price=Decimal("60.00"),
        market_price=Decimal("100.00"),
        cost_config=COST_CONFIG,
        scenario_pct=Decimal("0.05"),
    )
    assert result.sale_price == Decimal("105.00")
    assert result.margin == Decimal("-2.23")
    assert result.margin_pct == Decimal("-0.0213")


def test_profitable_at_market_price():
    result = calculate_margin(
        wholesale_price=Decimal("40.00"),
        market_price=Decimal("100.00"),
        cost_config=COST_CONFIG,
        scenario_pct=Decimal("0.00"),
    )
    assert result.sale_price == Decimal("100.00")
    assert result.net_revenue == Decimal("81.30")
    assert result.total_costs == Decimal("67.00")
    assert result.margin == Decimal("14.30")
    assert result.margin_pct == Decimal("0.1430")
