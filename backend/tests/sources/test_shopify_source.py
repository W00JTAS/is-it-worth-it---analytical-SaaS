from decimal import Decimal

import httpx
import pytest

from app.sources.base import CatalogSource
from app.sources.shopify_source import ShopifyCatalogSource, ShopifyApiError


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


def test_paginates_across_multiple_pages():
    def _page(product_id: str, variant_id: str, has_next: bool, cursor: str | None) -> dict:
        return {
            "edges": [
                {
                    "node": {
                        "id": product_id,
                        "title": f"Produkt {product_id}",
                        "productType": "Ogólne",
                        "variants": {
                            "edges": [
                                {
                                    "node": {
                                        "id": variant_id,
                                        "title": "Default Title",
                                        "price": "10.00",
                                        "barcode": None,
                                    }
                                }
                            ]
                        },
                    }
                }
            ],
            "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
        }

    client = _FakeClient(
        currency="PLN",
        pages=[
            _page("gid://shopify/Product/1", "gid://shopify/ProductVariant/10", True, "cursor-1"),
            _page("gid://shopify/Product/2", "gid://shopify/ProductVariant/20", False, None),
        ],
    )
    source = _make_source(client)

    products = source.fetch_products()

    assert [p.external_id for p in products] == [
        "gid://shopify/Product/1",
        "gid://shopify/Product/2",
    ]
    # 1 currency call + 2 page calls
    assert len(client.requests) == 3
    assert client.requests[1]["json"]["variables"]["cursor"] is None
    assert client.requests[2]["json"]["variables"]["cursor"] == "cursor-1"


class _RaisingStatusClient:
    """Simulates a non-2xx HTTP response: raise_for_status() raises."""

    def post(self, url, headers, json):
        request = httpx.Request("POST", url)
        response = httpx.Response(status_code=401, request=request)
        error = httpx.HTTPStatusError("unauthorized", request=request, response=response)

        class _Resp:
            def raise_for_status(self) -> None:
                raise error

            def json(self) -> dict:
                raise AssertionError("json() should not be called when raise_for_status() raises")

        return _Resp()


class _GraphQlErrorClient:
    def post(self, url, headers, json):
        return _FakeResponse({"errors": [{"message": "Access denied for currencyCode field."}]})


def test_raises_shopify_api_error_on_non_200_response():
    source = ShopifyCatalogSource(
        shop_domain="test-shop.myshopify.com",
        access_token="bad-token",
        tenant_id="t1",
        client=_RaisingStatusClient(),
    )

    with pytest.raises(ShopifyApiError):
        source.fetch_products()


def test_raises_shopify_api_error_on_graphql_errors_array():
    source = ShopifyCatalogSource(
        shop_domain="test-shop.myshopify.com",
        access_token="token",
        tenant_id="t1",
        client=_GraphQlErrorClient(),
    )

    with pytest.raises(ShopifyApiError, match="Access denied"):
        source.fetch_products()
