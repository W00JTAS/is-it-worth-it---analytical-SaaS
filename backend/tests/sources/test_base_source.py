from decimal import Decimal

import pytest

from app.sources.base import BaseCatalogSource, RawItem

VALID_EAN = "5901234123457"
INVALID_EAN = "5901234123458"
UPC_A = "698813001132"
PADDED_UPC_A = "0" + UPC_A


class FakeSource(BaseCatalogSource):
    SOURCE_NAME = "fake"

    def __init__(self, items: list[RawItem], tenant_id: str = "t1") -> None:
        super().__init__(tenant_id)
        self._items = items

    def _iter_raw_items(self):
        return iter(self._items)


def _item(**overrides) -> RawItem:
    defaults = dict(
        label="Row 2",
        external_id="2",
        variant_id=None,
        name="Łóżko",
        raw_price="100.00",
        raw_ean=VALID_EAN,
        raw_category="Meble",
        currency="PLN",
    )
    defaults.update(overrides)
    return RawItem(**defaults)


def test_maps_valid_item_to_product():
    source = FakeSource([_item()])
    products = source.fetch_products()
    assert len(products) == 1
    product = products[0]
    assert product.name == "Łóżko"
    assert product.wholesale_price == Decimal("100.00")
    assert product.ean == VALID_EAN
    assert product.category == "Meble"
    assert product.tenant_id == "t1"
    assert product.source == "fake"
    assert product.currency == "PLN"
    assert product.external_id == "2"
    assert product.variant_id is None


def test_skips_item_with_missing_name():
    source = FakeSource([_item(name="  ")])
    products = source.fetch_products()
    assert products == []
    assert any(w == "Row 2: missing name, skipped" for w in source.warnings)


def test_skips_item_with_invalid_price():
    source = FakeSource([_item(raw_price="not-a-price")])
    products = source.fetch_products()
    assert products == []
    assert any("invalid price" in w for w in source.warnings)


def test_skips_item_with_zero_price():
    source = FakeSource([_item(raw_price="0.00")])
    products = source.fetch_products()
    assert products == []
    assert any("zero price" in w for w in source.warnings)


def test_missing_category_defaults_to_uncategorized():
    source = FakeSource([_item(raw_category="")])
    products = source.fetch_products()
    assert products[0].category == "Bez kategorii"


def test_strips_whitespace_only_category_before_fallback():
    source = FakeSource([_item(raw_category="   ")])
    products = source.fetch_products()
    assert products[0].category == "Bez kategorii"


def test_zero_pads_valid_upc_a_barcode_to_ean13():
    source = FakeSource([_item(raw_ean=UPC_A)])
    products = source.fetch_products()
    assert products[0].ean == PADDED_UPC_A


def test_clears_ean_with_bad_checksum_but_keeps_item():
    source = FakeSource([_item(raw_ean=INVALID_EAN)])
    products = source.fetch_products()
    assert len(products) == 1
    assert products[0].ean is None
    assert any("invalid EAN checksum" in w for w in source.warnings)


def test_duplicate_ean_keeps_first_when_first_is_cheaper():
    source = FakeSource(
        [
            _item(label="Row 2", raw_price="100.00"),
            _item(label="Row 3", raw_price="200.00"),
        ]
    )
    products = source.fetch_products()
    assert len(products) == 1
    assert products[0].wholesale_price == Decimal("100.00")
    assert any("duplicate EAN" in w for w in source.warnings)


def test_duplicate_ean_replaces_with_cheaper_later_item():
    source = FakeSource(
        [
            _item(label="Row 2", raw_price="200.00"),
            _item(label="Row 3", raw_price="100.00"),
        ]
    )
    products = source.fetch_products()
    assert len(products) == 1
    assert products[0].wholesale_price == Decimal("100.00")
    assert any("duplicate EAN" in w for w in source.warnings)


def test_duplicate_ean_three_items_replaces_at_first_position():
    source = FakeSource(
        [
            _item(label="Row 2", external_id="2", raw_price="200.00"),
            _item(label="Row 3", external_id="3", raw_price="300.00"),
            _item(label="Row 4", external_id="4", raw_price="100.00"),
        ]
    )
    products = source.fetch_products()
    assert len(products) == 1
    assert products[0].external_id == "4"
    assert products[0].wholesale_price == Decimal("100.00")
    assert sum("duplicate EAN" in w for w in source.warnings) == 2


def test_subclass_without_source_name_raises_type_error_at_class_definition():
    # Must fire while the `class` statement itself executes -- i.e. from
    # `__init_subclass__` -- not deferred to instantiation or to the first
    # `_normalize` call during a fetch. Wrapping the `class` statement in
    # pytest.raises (rather than wrapping instantiation/fetch_products) is
    # what proves that: if the check were instead implemented in
    # `__init__` or inside `_normalize`, this class statement alone would
    # succeed and the test would fail with "DID NOT RAISE".
    with pytest.raises(TypeError, match="SOURCE_NAME"):

        class MissingSourceName(BaseCatalogSource):
            def _iter_raw_items(self):
                return iter(())


def test_subclass_with_source_name_does_not_raise():
    class HasSourceName(BaseCatalogSource):
        SOURCE_NAME = "has-name"

        def _iter_raw_items(self):
            return iter(())

    source = HasSourceName(tenant_id="t1")
    assert source.SOURCE_NAME == "has-name"


def test_items_without_ean_are_never_deduped():
    source = FakeSource(
        [
            _item(label="Row 2", external_id="2", raw_ean=""),
            _item(label="Row 3", external_id="3", raw_ean=""),
        ]
    )
    products = source.fetch_products()
    assert len(products) == 2


def test_rawitem_rejects_non_string_category():
    # A source that passes a raw vendor object (e.g. a WooCommerce
    # {"id": 9, "name": "Kuchnia"} category dict) instead of a plain string
    # must fail at construction, not with an opaque AttributeError deep
    # inside _normalize's .strip() call.
    with pytest.raises(TypeError):
        _item(raw_category={"id": 9, "name": "Kuchnia"})


def test_rawitem_rejects_non_string_variant_id():
    with pytest.raises(TypeError):
        _item(variant_id=123)


def test_rawitem_allows_none_variant_id():
    item = _item(variant_id=None)
    assert item.variant_id is None
