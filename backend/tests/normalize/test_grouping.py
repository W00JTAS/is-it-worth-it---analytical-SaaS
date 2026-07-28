from decimal import Decimal

from app.models.product import Product
from app.normalize.grouping import group_by_category


def _product(name: str, category: str) -> Product:
    return Product(
        tenant_id="t1",
        source="csv",
        external_id=name,
        variant_id=None,
        name=name,
        ean=None,
        wholesale_price=Decimal("10.00"),
        currency="PLN",
        category=category,
    )


def test_groups_products_by_category():
    products = [
        _product("Łóżko", "Meble"),
        _product("Stół", "Meble"),
        _product("Telefon", "Elektronika"),
    ]

    groups = group_by_category(products)

    assert set(groups.keys()) == {"Meble", "Elektronika"}
    assert [p.name for p in groups["Meble"]] == ["Łóżko", "Stół"]
    assert [p.name for p in groups["Elektronika"]] == ["Telefon"]


def test_empty_input_returns_empty_dict():
    assert group_by_category([]) == {}
