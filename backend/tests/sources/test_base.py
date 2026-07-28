from decimal import Decimal

from app.models.product import Product
from app.sources.base import CatalogSource


class DummySource:
    def fetch_products(self):
        return [
            Product(
                tenant_id="t1",
                source="dummy",
                external_id="1",
                variant_id=None,
                name="Test",
                ean=None,
                wholesale_price=Decimal("10.00"),
                currency="PLN",
                category="Test",
            )
        ]


class NotASource:
    pass


def test_dummy_source_conforms_to_catalog_source_protocol():
    assert isinstance(DummySource(), CatalogSource)


def test_class_without_fetch_products_does_not_conform():
    assert not isinstance(NotASource(), CatalogSource)
