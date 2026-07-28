from decimal import Decimal

from app.pricing.margin import CostConfig, calculate_margin_matrix

COST_CONFIG = CostConfig(
    commission_pct=Decimal("0.10"),
    shipping_cost=Decimal("15.00"),
    vat_pct=Decimal("0.23"),
    returns_pct=Decimal("0.02"),
)


def test_matrix_returns_four_scenarios_in_order():
    results = calculate_margin_matrix(
        wholesale_price=Decimal("40.00"),
        market_price=Decimal("100.00"),
        cost_config=COST_CONFIG,
    )

    assert [r.scenario_pct for r in results] == [
        Decimal("-0.10"),
        Decimal("-0.05"),
        Decimal("0.00"),
        Decimal("0.05"),
    ]
    assert [r.sale_price for r in results] == [
        Decimal("90.00"),
        Decimal("95.00"),
        Decimal("100.00"),
        Decimal("105.00"),
    ]
    assert [r.margin for r in results] == [
        Decimal("7.37"),
        Decimal("10.84"),
        Decimal("14.30"),
        Decimal("17.77"),
    ]
    assert [r.margin_pct for r in results] == [
        Decimal("0.0819"),
        Decimal("0.1141"),
        Decimal("0.1430"),
        Decimal("0.1692"),
    ]
