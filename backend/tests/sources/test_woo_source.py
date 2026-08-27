import json
from decimal import Decimal

import httpx
import pytest

from app.sources.base import CatalogSource
from app.sources.woo_source import WooCommerceCatalogSource, WooCommerceApiError


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self):
        return self._payload


class _FakeClient:
    """Serves a fixed sequence of responses, in call order: one currency
    call, then one response per `get()` call thereafter. Note a variable
    product's variations are paginated to completion (including the
    terminating empty page) as soon as that product is reached -- before
    the outer products pagination asks for its own next page."""

    def __init__(self, currency: str, responses: list):
        self._currency = currency
        self._responses = list(responses)
        self.requests: list[dict] = []

    def get(self, url, params=None):
        self.requests.append({"url": url, "params": params})
        if len(self.requests) == 1:
            return _FakeResponse({"code": self._currency})
        payload = self._responses.pop(0)
        return _FakeResponse(payload)


def _make_source(client: _FakeClient) -> WooCommerceCatalogSource:
    return WooCommerceCatalogSource(
        store_url="https://example-shop.pl",
        consumer_key="ck_test",
        consumer_secret="cs_test",
        tenant_id="t1",
        client=client,
    )


def test_implements_catalog_source_protocol():
    source = _make_source(_FakeClient(currency="PLN", responses=[[]]))
    assert isinstance(source, CatalogSource)


def test_maps_simple_product():
    client = _FakeClient(
        currency="PLN",
        responses=[
            [
                {
                    "id": 1,
                    "type": "simple",
                    "name": "Kubek termiczny",
                    "price": "49.99",
                    "global_unique_id": "5901234123457",
                    "categories": [{"id": 9, "name": "Kuchnia", "slug": "kuchnia"}],
                }
            ],
            [],
        ],
    )
    source = _make_source(client)

    products = source.fetch_products()

    assert len(products) == 1
    product = products[0]
    assert product.tenant_id == "t1"
    assert product.source == "woocommerce"
    assert product.external_id == "1"
    assert product.variant_id is None
    assert product.name == "Kubek termiczny"
    assert product.ean == "5901234123457"
    assert product.wholesale_price == Decimal("49.99")
    assert product.currency == "PLN"
    assert product.category == "Kuchnia"


def test_flattens_multiple_categories_to_first_one():
    client = _FakeClient(
        currency="PLN",
        responses=[
            [
                {
                    "id": 2,
                    "type": "simple",
                    "name": "Koszulka",
                    "price": "39.99",
                    "global_unique_id": "",
                    "categories": [
                        {"id": 12, "name": "Odzież", "slug": "odziez"},
                        {"id": 13, "name": "Męska", "slug": "meska"},
                    ],
                }
            ],
            [],
        ],
    )
    source = _make_source(client)

    products = source.fetch_products()

    assert products[0].category == "Odzież"


def test_maps_variable_product_with_variations():
    client = _FakeClient(
        currency="PLN",
        responses=[
            [
                {
                    "id": 3,
                    "type": "variable",
                    "name": "Koszulka",
                    "categories": [{"id": 12, "name": "Odzież", "slug": "odziez"}],
                }
            ],
            [
                {
                    "id": 30,
                    "price": "39.99",
                    "global_unique_id": "5901234123457",
                    "attributes": [{"id": 1, "name": "Rozmiar", "option": "S"}],
                },
                {
                    "id": 31,
                    "price": "39.99",
                    "global_unique_id": "5901234123458",
                    "attributes": [{"id": 1, "name": "Rozmiar", "option": "M"}],
                },
            ],
            [],
            [],
        ],
    )
    source = _make_source(client)

    products = source.fetch_products()

    assert [p.name for p in products] == ["Koszulka - Rozmiar: S", "Koszulka - Rozmiar: M"]
    assert [p.variant_id for p in products] == ["30", "31"]
    assert [p.external_id for p in products] == ["3", "3"]
    assert [p.category for p in products] == ["Odzież", "Odzież"]


def test_joins_multiple_attributes_in_variation_name():
    client = _FakeClient(
        currency="PLN",
        responses=[
            [{"id": 4, "type": "variable", "name": "Koszulka", "categories": []}],
            [
                {
                    "id": 40,
                    "price": "39.99",
                    "global_unique_id": "",
                    "attributes": [
                        {"id": 1, "name": "Rozmiar", "option": "S"},
                        {"id": 2, "name": "Kolor", "option": "Czarny"},
                    ],
                }
            ],
            [],
            [],
        ],
    )
    source = _make_source(client)

    products = source.fetch_products()

    assert products[0].name == "Koszulka - Rozmiar: S, Kolor: Czarny"


def test_skips_variation_when_parent_product_name_is_blank():
    # A blank product name composed with a non-blank attribute suffix would
    # still look non-blank (e.g. "- Rozmiar: S"), silently defeating
    # BaseCatalogSource's missing-name check -- must be forced blank instead.
    client = _FakeClient(
        currency="PLN",
        responses=[
            [{"id": 5, "type": "variable", "name": "   ", "categories": []}],
            [
                {
                    "id": 50,
                    "price": "10.00",
                    "global_unique_id": "",
                    "attributes": [{"id": 1, "name": "Rozmiar", "option": "S"}],
                }
            ],
            [],
            [],
        ],
    )
    source = _make_source(client)

    products = source.fetch_products()

    assert products == []
    assert any("missing name" in w for w in source.warnings)


def test_skips_grouped_and_external_products_with_warning():
    client = _FakeClient(
        currency="PLN",
        responses=[
            [
                {"id": 6, "type": "grouped", "name": "Zestaw", "categories": []},
                {"id": 7, "type": "external", "name": "Afiliacja", "categories": []},
            ],
            [],
        ],
    )
    source = _make_source(client)

    products = source.fetch_products()

    assert products == []
    assert any("Product 6" in w and "grouped" in w for w in source.warnings)
    assert any("Product 7" in w and "external" in w for w in source.warnings)


def test_paginates_products_across_multiple_pages():
    client = _FakeClient(
        currency="PLN",
        responses=[
            [{"id": 8, "type": "simple", "name": "Produkt 8", "price": "10.00",
              "global_unique_id": "", "categories": []}],
            [{"id": 9, "type": "simple", "name": "Produkt 9", "price": "10.00",
              "global_unique_id": "", "categories": []}],
            [],
        ],
    )
    source = _make_source(client)

    products = source.fetch_products()

    assert [p.external_id for p in products] == ["8", "9"]
    # 1 currency call + 3 product-page calls (2 with data, 1 empty to stop)
    assert len(client.requests) == 4
    assert client.requests[1]["params"]["page"] == 1
    assert client.requests[2]["params"]["page"] == 2
    assert client.requests[3]["params"]["page"] == 3


def test_paginates_variations_of_a_variable_product():
    client = _FakeClient(
        currency="PLN",
        responses=[
            [{"id": 10, "type": "variable", "name": "Produkt", "categories": []}],
            [
                {"id": 100, "price": "10.00", "global_unique_id": "", "attributes": []},
            ],
            [
                {"id": 101, "price": "11.00", "global_unique_id": "", "attributes": []},
            ],
            [],
            [],
        ],
    )
    source = _make_source(client)

    products = source.fetch_products()

    assert [p.variant_id for p in products] == ["100", "101"]


def test_dedups_same_ean_across_variations_keeping_cheaper_price():
    client = _FakeClient(
        currency="PLN",
        responses=[
            [{"id": 11, "type": "variable", "name": "Kubek",
              "categories": [{"id": 9, "name": "Kuchnia", "slug": "kuchnia"}]}],
            [
                {
                    "id": 110,
                    "price": "49.99",
                    "global_unique_id": "5901234123457",
                    "attributes": [{"id": 1, "name": "Rozmiar", "option": "S"}],
                },
                {
                    "id": 111,
                    "price": "39.99",
                    "global_unique_id": "5901234123457",
                    "attributes": [{"id": 1, "name": "Rozmiar", "option": "M"}],
                },
            ],
            [],
            [],
        ],
    )
    source = _make_source(client)

    products = source.fetch_products()

    assert len(products) == 1
    assert products[0].wholesale_price == Decimal("39.99")
    assert products[0].variant_id == "111"
    assert any("duplicate EAN" in w for w in source.warnings)


def test_raises_woocommerce_api_error_when_pagination_never_terminates():
    # A page number that never comes back empty (e.g. a caching proxy or CDN
    # that strips/ignores the `page` query param and always serves page 1)
    # must not hang the fetch or grow `products` without bound.
    class _StuckPageClient:
        def get(self, url, params=None):
            if "currencies" in url:
                return _FakeResponse({"code": "PLN"})
            return _FakeResponse(
                [
                    {
                        "id": 1,
                        "type": "simple",
                        "name": "Produkt",
                        "price": "10.00",
                        "global_unique_id": "",
                        "categories": [],
                    }
                ]
            )

    source = _make_source(_StuckPageClient())

    with pytest.raises(WooCommerceApiError, match="did not terminate"):
        source.fetch_products()


class _RaisingStatusClient:
    def get(self, url, params=None):
        request = httpx.Request("GET", url)
        response = httpx.Response(status_code=401, request=request)
        error = httpx.HTTPStatusError("unauthorized", request=request, response=response)

        class _Resp:
            def raise_for_status(self) -> None:
                raise error

            def json(self):
                raise AssertionError("json() should not be called when raise_for_status() raises")

        return _Resp()


def test_raises_woocommerce_api_error_on_non_200_response():
    source = WooCommerceCatalogSource(
        store_url="https://example-shop.pl",
        consumer_key="bad",
        consumer_secret="bad",
        tenant_id="t1",
        client=_RaisingStatusClient(),
    )

    with pytest.raises(WooCommerceApiError):
        source.fetch_products()


class _JsonDecodeErrorClient:
    def get(self, url, params=None):
        class _Resp:
            def raise_for_status(self) -> None:
                pass

            def json(self):
                raise json.JSONDecodeError("Expecting value", "<html>", 0)

        return _Resp()


def test_raises_woocommerce_api_error_on_non_json_response():
    source = WooCommerceCatalogSource(
        store_url="https://example-shop.pl",
        consumer_key="ck",
        consumer_secret="cs",
        tenant_id="t1",
        client=_JsonDecodeErrorClient(),
    )

    with pytest.raises(WooCommerceApiError):
        source.fetch_products()


def test_raises_woocommerce_api_error_on_non_list_products_response():
    client = _FakeClient(
        currency="PLN",
        responses=[{"code": "woocommerce_rest_cannot_view", "message": "Forbidden"}],
    )
    source = _make_source(client)

    with pytest.raises(WooCommerceApiError):
        source.fetch_products()


def test_raises_woocommerce_api_error_on_malformed_currency_response():
    class _BadCurrencyClient:
        def get(self, url, params=None):
            return _FakeResponse({"unexpected": "shape"})

    source = _make_source(_BadCurrencyClient())

    with pytest.raises(WooCommerceApiError):
        source.fetch_products()


def test_raises_woocommerce_api_error_on_product_missing_id():
    client = _FakeClient(
        currency="PLN",
        responses=[[{"type": "simple", "name": "Produkt bez id", "price": "10.00"}]],
    )
    source = _make_source(client)

    with pytest.raises(WooCommerceApiError):
        source.fetch_products()


def test_raises_woocommerce_api_error_on_non_object_items_in_products_page():
    client = _FakeClient(currency="PLN", responses=[["not-a-product-object"]])
    source = _make_source(client)

    with pytest.raises(WooCommerceApiError):
        source.fetch_products()


def test_raises_woocommerce_api_error_on_variation_missing_id():
    client = _FakeClient(
        currency="PLN",
        responses=[
            [{"id": 12, "type": "variable", "name": "Produkt", "categories": []}],
            [{"price": "10.00", "attributes": []}],
        ],
    )
    source = _make_source(client)

    with pytest.raises(WooCommerceApiError):
        source.fetch_products()
