import os

import pytest

from app.sources.woo_source import WooCommerceCatalogSource

pytestmark = pytest.mark.skipif(
    not (
        os.environ.get("WOO_TEST_STORE_URL")
        and os.environ.get("WOO_TEST_CONSUMER_KEY")
        and os.environ.get("WOO_TEST_CONSUMER_SECRET")
    ),
    reason="WOO_TEST_STORE_URL/WOO_TEST_CONSUMER_KEY/WOO_TEST_CONSUMER_SECRET not set — export "
    "them to run this opt-in test against a real WooCommerce dev store",
)


def test_fetch_products_maps_a_real_catalog():
    source = WooCommerceCatalogSource(
        store_url=os.environ["WOO_TEST_STORE_URL"],
        consumer_key=os.environ["WOO_TEST_CONSUMER_KEY"],
        consumer_secret=os.environ["WOO_TEST_CONSUMER_SECRET"],
        tenant_id="live-smoke-test",
    )

    products = source.fetch_products()

    assert len(products) > 0
    for product in products:
        assert product.wholesale_price > 0
        assert product.currency
