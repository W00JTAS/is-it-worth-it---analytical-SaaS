from decimal import Decimal

from app.sources.base import CatalogSource
from app.sources.shopify_source import ShopifyCatalogSource


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    """Returns the currency-query response on the first call, then one
    products-page response per call thereafter, in order — matching
    ShopifyCatalogSource's fixed call order: one currency query, then one
    products query per page."""

    def __init__(self, currency: str, pages: list[dict]):
        self._currency = currency
        self._pages = list(pages)
        self.requests: list[dict] = []

    def post(self, url, headers, json):
        self.requests.append({"url": url, "headers": headers, "json": json})
        if len(self.requests) == 1:
            return _FakeResponse({"data": {"shop": {"currencyCode": self._currency}}})
        page = self._pages.pop(0)
        return _FakeResponse({"data": {"products": page}})


def _single_product_page(node: dict, has_next: bool = False, cursor: str | None = None) -> dict:
    return {
        "edges": [{"node": node}],
        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
    }


def _make_source(client: _FakeClient) -> ShopifyCatalogSource:
    return ShopifyCatalogSource(
        shop_domain="test-shop.myshopify.com",
        access_token="token",
        tenant_id="t1",
        client=client,
    )


def test_implements_catalog_source_protocol():
    source = _make_source(_FakeClient(currency="PLN", pages=[]))
    assert isinstance(source, CatalogSource)


def test_maps_single_variant_product():
    client = _FakeClient(
        currency="PLN",
        pages=[
            _single_product_page(
                {
                    "id": "gid://shopify/Product/1",
                    "title": "Kubek termiczny",
                    "productType": "Kuchnia",
                    "variants": {
                        "edges": [
                            {
                                "node": {
                                    "id": "gid://shopify/ProductVariant/10",
                                    "title": "Default Title",
                                    "price": "49.99",
                                    "barcode": "5901234123457",
                                }
                            }
                        ]
                    },
                }
            )
        ],
    )
    source = _make_source(client)

    products = source.fetch_products()

    assert len(products) == 1
    product = products[0]
    assert product.tenant_id == "t1"
    assert product.source == "shopify"
    assert product.external_id == "gid://shopify/Product/1"
    assert product.variant_id == "gid://shopify/ProductVariant/10"
    assert product.name == "Kubek termiczny"
    assert product.ean == "5901234123457"
    assert product.wholesale_price == Decimal("49.99")
    assert product.currency == "PLN"
    assert product.category == "Kuchnia"


def test_names_non_default_variants_with_variant_title():
    client = _FakeClient(
        currency="PLN",
        pages=[
            _single_product_page(
                {
                    "id": "gid://shopify/Product/2",
                    "title": "Koszulka",
                    "productType": "Odzież",
                    "variants": {
                        "edges": [
                            {
                                "node": {
                                    "id": "gid://shopify/ProductVariant/20",
                                    "title": "S",
                                    "price": "39.99",
                                    "barcode": None,
                                }
                            },
                            {
                                "node": {
                                    "id": "gid://shopify/ProductVariant/21",
                                    "title": "M",
                                    "price": "39.99",
                                    "barcode": None,
                                }
                            },
                        ]
                    },
                }
            )
        ],
    )
    source = _make_source(client)

    products = source.fetch_products()

    assert [p.name for p in products] == ["Koszulka - S", "Koszulka - M"]
    assert [p.variant_id for p in products] == [
        "gid://shopify/ProductVariant/20",
        "gid://shopify/ProductVariant/21",
    ]


def test_skips_zero_price_variant_and_falls_back_category():
    client = _FakeClient(
        currency="PLN",
        pages=[
            _single_product_page(
                {
                    "id": "gid://shopify/Product/3",
                    "title": "Darmowa próbka",
                    "productType": "",
                    "variants": {
                        "edges": [
                            {
                                "node": {
                                    "id": "gid://shopify/ProductVariant/30",
                                    "title": "Default Title",
                                    "price": "0.00",
                                    "barcode": None,
                                }
                            }
                        ]
                    },
                }
            )
        ],
    )
    source = _make_source(client)

    products = source.fetch_products()

    assert products == []
    assert any("zero price" in w for w in source.warnings)


def test_clears_invalid_barcode_checksum():
    client = _FakeClient(
        currency="PLN",
        pages=[
            _single_product_page(
                {
                    "id": "gid://shopify/Product/4",
                    "title": "Zegarek",
                    "productType": "Akcesoria",
                    "variants": {
                        "edges": [
                            {
                                "node": {
                                    "id": "gid://shopify/ProductVariant/40",
                                    "title": "Default Title",
                                    "price": "199.00",
                                    "barcode": "1234567890123",
                                }
                            }
                        ]
                    },
                }
            )
        ],
    )
    source = _make_source(client)

    products = source.fetch_products()

    assert products[0].ean is None
    assert any("invalid EAN checksum" in w for w in source.warnings)
