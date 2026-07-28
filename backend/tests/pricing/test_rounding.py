from decimal import Decimal

from app.pricing.margin import round_money, round_pct


def test_round_money_rounds_half_up_to_two_places():
    assert round_money(Decimal("81.300813008")) == Decimal("81.30")
    assert round_money(Decimal("-5.699186991")) == Decimal("-5.70")


def test_round_pct_rounds_half_up_to_four_places():
    assert round_pct(Decimal("-0.05699186991")) == Decimal("-0.0570")
    assert round_pct(Decimal("0.14300813008")) == Decimal("0.1430")
