import dataclasses
from decimal import Decimal

import pytest

from app.models.product import Product


def _make_product(**overrides) -> Product:
    defaults = dict(
        tenant_id="t1",
        source="csv",
        external_id="1",
        variant_id=None,
        name="Test Product",
        ean=None,
        wholesale_price=Decimal("10.00"),
        currency="PLN",
        category="Test",
    )
    defaults.update(overrides)
    return Product(**defaults)


def test_product_holds_expected_fields():
    product = _make_product()
    assert product.name == "Test Product"
    assert product.wholesale_price == Decimal("10.00")


def test_product_is_immutable():
    product = _make_product()
    with pytest.raises(dataclasses.FrozenInstanceError):
        product.name = "Changed"
