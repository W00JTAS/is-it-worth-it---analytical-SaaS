# Phase 6: ShopifySource Sketch Implementation Plan

**Goal:** Build a read-only `ShopifyCatalogSource` implementing the existing `CatalogSource`
protocol against Shopify's GraphQL Admin API, to prove (or disprove) that the abstraction survives
contact with a real second source — no OAuth, no hosting, no write-back.

**Architecture:** One class, `ShopifyCatalogSource` (`backend/app/sources/shopify_source.py`),
mirroring `CsvCatalogSource`'s constructor-holds-state / `fetch_products()` shape and
`PerplexityProvider`'s injected-`httpx.Client` testability pattern. It issues one GraphQL query for
the shop's currency, then paginates a `products(first, after)` query, mapping **each variant** to
one `Product` (this is the field the CSV source never populated).

**Tech Stack:** Python, `httpx` (already a dependency), `pytest`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-26-shopify-source-sketch-design.md`

## Global Constraints

- GraphQL Admin API only, never REST (REST is legacy/maintenance-mode as of 2024-10-01).
- Default API version `2026-07`, overridable via constructor parameter — never hardcode a version
  with no override.
- Auth via `X-Shopify-Access-Token` header (custom-app access token) — no OAuth code at all.
- Reuse `app.normalize.money.parse_price` and `app.normalize.ean.is_valid_ean` — do not write
  Shopify-specific parsing for price strings or barcode checksums.
- No retry/backoff, no rate-limit handling, no `CatalogSink`, no webhooks — out of scope.
- Test doubles follow this repo's existing convention exactly: hand-written duck-typed fake
  classes (`_FakeClient` / `_FakeResponse`), never `httpx.MockTransport`.
- The live smoke test must never run in default `pytest`/CI — gated by
  `pytest.mark.skipif` on env vars, same pattern as `tests/providers/test_perplexity_live.py`.

---

### Task 1: Core mapping — single page, happy path + skip rules

**Files:**
- Create: `backend/app/sources/shopify_source.py`
- Test: `backend/tests/sources/test_shopify_source.py`

**Interfaces:**
- Consumes: `app.models.product.Product` (dataclass: `tenant_id, source, external_id, variant_id,
  name, ean, wholesale_price: Decimal, currency, category`); `app.sources.base.CatalogSource`
  (Protocol, `fetch_products() -> Iterable[Product]`); `app.normalize.money.parse_price(raw: str) ->
  Decimal` (raises `InvalidPriceError`); `app.normalize.ean.is_valid_ean(code: str) -> bool`.
- Produces: `ShopifyCatalogSource(shop_domain: str, access_token: str, tenant_id: str, client:
  httpx.Client | None = None, api_version: str = "2026-07")` with `.fetch_products() ->
  list[Product]` and `.warnings: list[str]`. Later tasks (2, 3) modify `fetch_products()` and
  `_post()` on this same class — do not rename either method.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/sources/test_shopify_source.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/sources/test_shopify_source.py -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'app.sources.shopify_source'`

- [ ] **Step 3: Write the minimal implementation**

Create `backend/app/sources/shopify_source.py`:

```python
from __future__ import annotations

from typing import Any

import httpx

from app.models.product import Product
from app.normalize.ean import is_valid_ean
from app.normalize.money import InvalidPriceError, parse_price

DEFAULT_API_VERSION = "2026-07"

CURRENCY_QUERY = "{ shop { currencyCode } }"

PRODUCTS_QUERY = """
query($cursor: String) {
  products(first: 50, after: $cursor) {
    edges {
      node {
        id
        title
        productType
        variants(first: 100) {
          edges {
            node {
              id
              title
              price
              barcode
            }
          }
        }
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""

class ShopifyCatalogSource:
    SOURCE_NAME = "shopify"

    def __init__(
        self,
        shop_domain: str,
        access_token: str,
        tenant_id: str,
        client: httpx.Client | None = None,
        api_version: str = DEFAULT_API_VERSION,
    ) -> None:
        self.shop_domain = shop_domain
        self.access_token = access_token
        self.tenant_id = tenant_id
        self.api_version = api_version
        self._client = client or httpx.Client(timeout=30.0)
        self.warnings: list[str] = []

    @property
    def _url(self) -> str:
        return f"https://{self.shop_domain}/admin/api/{self.api_version}/graphql.json"

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "X-Shopify-Access-Token": self.access_token,
            "Content-Type": "application/json",
        }

    def _post(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self._client.post(
            self._url,
            headers=self._headers,
            json={"query": query, "variables": variables or {}},
        )
        response.raise_for_status()
        body = response.json()
        return body["data"]

    def fetch_products(self) -> list[Product]:
        currency = self._post(CURRENCY_QUERY)["shop"]["currencyCode"]

        data = self._post(PRODUCTS_QUERY, {"cursor": None})["products"]
        products: list[Product] = []
        for edge in data["edges"]:
            products.extend(self._map_product(edge["node"], currency))

        return products

    def _map_product(self, node: dict[str, Any], currency: str) -> list[Product]:
        product_id = node["id"]
        title = node["title"]
        category = node.get("productType") or "Bez kategorii"

        mapped: list[Product] = []
        for variant_edge in node["variants"]["edges"]:
            variant = variant_edge["node"]
            variant_id = variant["id"]

            raw_price = variant.get("price") or ""
            try:
                wholesale_price = parse_price(raw_price)
            except InvalidPriceError:
                self.warnings.append(
                    f"Product {product_id}, variant {variant_id}: invalid price "
                    f"'{raw_price}', skipped"
                )
                continue

            if wholesale_price == 0:
                self.warnings.append(
                    f"Product {product_id}, variant {variant_id}: zero price, skipped"
                )
                continue

            variant_title = variant.get("title") or "Default Title"
            name = title if variant_title == "Default Title" else f"{title} - {variant_title}"

            raw_barcode = (variant.get("barcode") or "").strip()
            ean: str | None = None
            if raw_barcode:
                if is_valid_ean(raw_barcode):
                    ean = raw_barcode
                else:
                    self.warnings.append(
                        f"Product {product_id}, variant {variant_id}: invalid EAN "
                        f"checksum '{raw_barcode}', ean cleared"
                    )

            mapped.append(
                Product(
                    tenant_id=self.tenant_id,
                    source=self.SOURCE_NAME,
                    external_id=product_id,
                    variant_id=variant_id,
                    name=name,
                    ean=ean,
                    wholesale_price=wholesale_price,
                    currency=currency,
                    category=category,
                )
            )

        return mapped
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/sources/test_shopify_source.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/sources/shopify_source.py tests/sources/test_shopify_source.py
git commit -m "$(cat <<'EOF'
Add ShopifyCatalogSource: single-page mapping + skip rules

Maps each Shopify variant to one Product (external_id=product GID,
variant_id=variant GID), reusing normalize.money/normalize.ean for
price and barcode handling. No pagination or error wrapping yet.
EOF
)"
```

---

### Task 2: Pagination across multiple pages

**Files:**
- Modify: `backend/app/sources/shopify_source.py` (`fetch_products` method)
- Test: `backend/tests/sources/test_shopify_source.py` (append)

**Interfaces:**
- Consumes: `ShopifyCatalogSource._post`, `ShopifyCatalogSource._map_product` (both from Task 1,
  unchanged signatures).
- Produces: `fetch_products()` now loops until `pageInfo.hasNextPage` is `False`, passing
  `pageInfo.endCursor` as the next `cursor` variable. No new public interface — same signature.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/sources/test_shopify_source.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/sources/test_shopify_source.py::test_paginates_across_multiple_pages -v`
Expected: FAIL — only 2 requests recorded (currency + first page), second product missing,
because `fetch_products()` currently fetches only one page.

- [ ] **Step 3: Implement pagination**

In `backend/app/sources/shopify_source.py`, replace the body of `fetch_products`:

```python
    def fetch_products(self) -> list[Product]:
        currency = self._post(CURRENCY_QUERY)["shop"]["currencyCode"]

        products: list[Product] = []
        cursor: str | None = None
        while True:
            data = self._post(PRODUCTS_QUERY, {"cursor": cursor})["products"]
            for edge in data["edges"]:
                products.extend(self._map_product(edge["node"], currency))

            page_info = data["pageInfo"]
            if not page_info["hasNextPage"]:
                break
            cursor = page_info["endCursor"]

        return products
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/sources/test_shopify_source.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/sources/shopify_source.py tests/sources/test_shopify_source.py
git commit -m "$(cat <<'EOF'
Add pagination to ShopifyCatalogSource.fetch_products

Loops the products query on pageInfo.hasNextPage/endCursor until
exhausted, instead of stopping after the first page.
EOF
)"
```

---

### Task 3: Error handling (`ShopifyApiError`)

**Files:**
- Modify: `backend/app/sources/shopify_source.py` (`_post` method, plus new exception class)
- Test: `backend/tests/sources/test_shopify_source.py` (append)

**Interfaces:**
- Produces: `class ShopifyApiError(Exception)`, importable as
  `app.sources.shopify_source.ShopifyApiError`. `_post()` now raises it on a non-2xx HTTP response
  or a GraphQL `errors` array in the response body, instead of propagating `httpx.HTTPError` or
  returning malformed data.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/sources/test_shopify_source.py`:

```python
import httpx
import pytest

from app.sources.shopify_source import ShopifyApiError

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/sources/test_shopify_source.py -k "api_error" -v`
Expected: FAIL — `test_raises_shopify_api_error_on_non_200_response` fails with
`httpx.HTTPStatusError` propagating uncaught (not `ShopifyApiError`); the import of
`ShopifyApiError` itself fails with `ImportError` since the class doesn't exist yet.

- [ ] **Step 3: Implement error wrapping**

In `backend/app/sources/shopify_source.py`, add the exception class near the top (after the query
constants) and replace `_post`:

```python
class ShopifyApiError(Exception):
    pass
```

```python
    def _post(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = self._client.post(
                self._url,
                headers=self._headers,
                json={"query": query, "variables": variables or {}},
            )
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError as exc:
            raise ShopifyApiError(f"Shopify request failed: {exc}") from exc

        if "errors" in body:
            messages = "; ".join(e.get("message", str(e)) for e in body["errors"])
            raise ShopifyApiError(f"Shopify GraphQL error: {messages}")

        return body["data"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/sources/test_shopify_source.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/sources/shopify_source.py tests/sources/test_shopify_source.py
git commit -m "$(cat <<'EOF'
Wrap Shopify HTTP/GraphQL failures in ShopifyApiError

A non-2xx response or a GraphQL errors array now raises a clear
ShopifyApiError instead of an uncaught httpx.HTTPError or silently
malformed data.
EOF
)"
```

---

### Task 4: Live smoke test against a real dev store

**Files:**
- Create: `backend/tests/sources/test_shopify_source_live.py`

**Interfaces:**
- Consumes: `ShopifyCatalogSource` (Tasks 1-3, unchanged), reads `SHOPIFY_TEST_SHOP` and
  `SHOPIFY_TEST_TOKEN` from the environment.
- Produces: nothing consumed by later tasks — this is the terminal task and the phase's
  definition-of-done check.

- [ ] **Step 1: Write the test**

Create `backend/tests/sources/test_shopify_source_live.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it is skipped by default**

Run: `cd backend && pytest tests/sources/test_shopify_source_live.py -v`
Expected: SKIPPED — 1 skipped, reason "SHOPIFY_TEST_SHOP/SHOPIFY_TEST_TOKEN not set"
(no `SHOPIFY_TEST_SHOP`/`SHOPIFY_TEST_TOKEN` are set in this environment).

- [ ] **Step 3: Run the full backend test suite to confirm nothing else broke**

Run: `cd backend && pytest -v`
Expected: PASS, plus the 1 new skip from Step 2 — no regressions in the pre-existing suite.

- [ ] **Step 4: Commit**

```bash
cd backend && git add tests/sources/test_shopify_source_live.py
git commit -m "$(cat <<'EOF'
Add live smoke test for ShopifyCatalogSource

Opt-in only (skipif on SHOPIFY_TEST_SHOP/SHOPIFY_TEST_TOKEN), mirroring
test_perplexity_live.py's gating pattern. This is the phase's actual
definition-of-done check: run it manually once a real dev store with a
multi-variant product exists (see the design spec's "Setup required"
section for the one-time store setup steps), and update the design
spec with the result — pass, or what had to change if it didn't.
EOF
)"
```
