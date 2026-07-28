from decimal import Decimal

import pytest

from app.normalize.money import InvalidPriceError, parse_price


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("12,50", Decimal("12.50")),
        ("12.50", Decimal("12.50")),
        ("12,50 zł", Decimal("12.50")),
        ("1 234,56", Decimal("1234.56")),
        ("10", Decimal("10")),
    ],
)
def test_parse_price_valid_inputs(raw, expected):
    assert parse_price(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "-5,00"])
def test_parse_price_rejects_invalid_inputs(raw):
    with pytest.raises(InvalidPriceError):
        parse_price(raw)
