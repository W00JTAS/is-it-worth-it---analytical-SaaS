import os

import pytest

from app.sources.shopify_source import ShopifyCatalogSource

pytestmark = pytest.mark.skipif(
    not (os.environ.get("SHOPIFY_TEST_SHOP") and os.environ.get("SHOPIFY_TEST_TOKEN")),
    reason="SHOPIFY_TEST_SHOP/SHOPIFY_TEST_TOKEN not set — export them to run this opt-in test "
    "against a real Shopify dev store",
)


def test_fetch_products_maps_a_real_multi_variant_catalog():
    source = ShopifyCatalogSource(
        shop_domain=os.environ["SHOPIFY_TEST_SHOP"],
        access_token=os.environ["SHOPIFY_TEST_TOKEN"],
        tenant_id="live-smoke-test",
    )

    products = source.fetch_products()

    assert len(products) > 0
    assert any(p.variant_id is not None for p in products)
    for product in products:
        assert product.wholesale_price > 0
        assert product.currency
