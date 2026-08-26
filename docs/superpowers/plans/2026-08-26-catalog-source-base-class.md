# Shared CatalogSource Normalization Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the five normalization invariants currently duplicated by hand in
`CsvCatalogSource` and `ShopifyCatalogSource` (blank-name skip, zero/invalid-price skip, category
strip+fallback, UPC-A padding + EAN checksum, EAN dedup keeping the cheapest) into a shared
`BaseCatalogSource` template-method class, so a new source (e.g. WooCommerce) cannot omit any of
them — then write the `add-catalog-source` skill that walks through adding one.

**Architecture:** `BaseCatalogSource` (new ABC in `app/sources/base.py`) owns `fetch_products()`
end-to-end: iterate `RawItem`s, normalize each into a `Product` or drop it with a warning, dedup by
EAN. Concrete sources implement only `_iter_raw_items() -> Iterable[RawItem]`, translating their
own format (CSV rows, Shopify GraphQL variant nodes) into raw, unvalidated field values. EAN
padding/checksum logic is further extracted into a pure `normalize_ean()` function in
`app/normalize/ean.py`, callable and testable independent of any source.

**Tech Stack:** Python 3.14, pytest, existing `app.normalize.money.parse_price` /
`app.normalize.ean.is_valid_ean` (unchanged).

**Spec:** `docs/superpowers/specs/2026-08-26-catalog-source-base-class-design.md`

## Global Constraints

- `CsvCatalogSource`'s public constructor signature and every warning message it currently emits
  must be byte-for-byte unchanged — it has no design license to change (per spec: "Constructor and
  `EmptyCsvError` are unchanged").
- `ShopifyCatalogSource`'s public constructor signature is unchanged. Its only sanctioned message
  change is the missing-name/-title wording and per-variant granularity called out in the spec.
- No normalization logic (name/price/category/EAN checks, dedup) may exist in `csv_source.py` or
  `shopify_source.py` after this plan — grep for
  `strip()\|is_valid_ean\|len(raw\|seen_eans\|Bez kategorii` in those two files must return nothing
  outside of `_iter_raw_items`/`_map_product` passing raw values straight through (Definition of
  Done in the spec).
- The existing `CatalogSource` `Protocol` in `app/sources/base.py` is not removed or altered —
  `BaseCatalogSource` must keep satisfying it structurally.
- `Product` (`app/models/product.py`) is not modified.

---

### Task 1: `normalize_ean` — pure EAN normalization function

**Files:**
- Modify: `backend/app/normalize/ean.py`
- Test: `backend/tests/normalize/test_ean.py`

**Interfaces:**
- Produces: `normalize_ean(raw: str) -> tuple[str | None, str | None]` — returns `(ean, warning)`.
  `ean` is the zero-padded, checksum-validated code, or `None` if `raw` is blank/absent or fails
  the checksum. `warning` is `None` unless the checksum failed, in which case it is
  `f"invalid EAN checksum '{code}', ean cleared"` (no label prefix — callers prepend their own).
  Consumed by Task 2's `BaseCatalogSource._normalize`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/normalize/test_ean.py`:

```python
from app.normalize.ean import is_valid_ean, normalize_ean


def test_normalize_ean_pads_upc_a_to_ean13():
    ean, warning = normalize_ean("698813001132")
    assert ean == "0698813001132"
    assert warning is None


def test_normalize_ean_returns_warning_on_bad_checksum():
    ean, warning = normalize_ean("5901234123458")
    assert ean is None
    assert warning == "invalid EAN checksum '5901234123458', ean cleared"


def test_normalize_ean_returns_none_for_blank_input():
    ean, warning = normalize_ean("")
    assert ean is None
    assert warning is None


def test_normalize_ean_strips_whitespace():
    ean, warning = normalize_ean("  5901234123457  ")
    assert ean == "5901234123457"
    assert warning is None


def test_normalize_ean_passes_through_valid_ean13_unchanged():
    ean, warning = normalize_ean("5901234123457")
    assert ean == "5901234123457"
    assert warning is None
```

Replace the file's existing `from app.normalize.ean import is_valid_ean` line at the top with the
combined import shown above (don't duplicate the import).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/normalize/test_ean.py -v`
Expected: the 5 new tests FAIL with `ImportError: cannot import name 'normalize_ean'`.

- [ ] **Step 3: Implement `normalize_ean`**

Append to `backend/app/normalize/ean.py` (after the existing `is_valid_ean`):

```python
def normalize_ean(raw: str) -> tuple[str | None, str | None]:
    code = raw.strip()
    if not code:
        return None, None

    if len(code) == 12 and code.isdigit():
        # UPC-A is numerically identical to EAN-13 with a leading zero.
        code = "0" + code

    if is_valid_ean(code):
        return code, None

    return None, f"invalid EAN checksum '{code}', ean cleared"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/normalize/test_ean.py -v`
Expected: all tests PASS (11 total: 6 existing `is_valid_ean` + 5 new).

- [ ] **Step 5: Commit**

```bash
git add backend/app/normalize/ean.py backend/tests/normalize/test_ean.py
git commit -m "Add normalize_ean: shared UPC-A padding + checksum validation"
```

---

### Task 2: `RawItem` + `BaseCatalogSource`

**Files:**
- Modify: `backend/app/sources/base.py`
- Test: `backend/tests/sources/test_base_source.py` (new)

**Interfaces:**
- Consumes: `normalize_ean` from Task 1; `Product` from `app.models.product` (unchanged);
  `parse_price`/`InvalidPriceError` from `app.normalize.money` (unchanged).
- Produces: `RawItem` dataclass (`label: str, external_id: str, variant_id: str | None, name: str,
  raw_price: str, raw_ean: str, raw_category: str, currency: str`); `BaseCatalogSource(ABC)` with
  abstract `_iter_raw_items(self) -> Iterable[RawItem]`, concrete `fetch_products(self) ->
  list[Product]`, `warnings: list[str]`, `tenant_id: str`, class attribute `SOURCE_NAME: str`.
  Consumed by Tasks 3 and 4.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/sources/test_base_source.py`:

```python
from decimal import Decimal

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


def test_duplicate_ean_three_items_keeps_cheapest_at_first_position():
    source = FakeSource(
        [
            _item(label="Row 2", external_id="2", raw_price="200.00"),
            _item(label="Row 3", external_id="3", raw_price="300.00"),
            _item(label="Row 4", external_id="4", raw_price="100.00"),
        ]
    )
    products = source.fetch_products()
    assert len(products) == 1
    assert products[0].external_id == "2"
    assert products[0].wholesale_price == Decimal("100.00")
    assert sum("duplicate EAN" in w for w in source.warnings) == 2


def test_items_without_ean_are_never_deduped():
    source = FakeSource(
        [
            _item(label="Row 2", external_id="2", raw_ean=""),
            _item(label="Row 3", external_id="3", raw_ean=""),
        ]
    )
    products = source.fetch_products()
    assert len(products) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/sources/test_base_source.py -v`
Expected: FAIL with `ImportError: cannot import name 'BaseCatalogSource'` (or `RawItem`).

- [ ] **Step 3: Implement `RawItem` and `BaseCatalogSource`**

Replace the full contents of `backend/app/sources/base.py` with:

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, Protocol, runtime_checkable

from app.models.product import Product
from app.normalize.ean import normalize_ean
from app.normalize.money import InvalidPriceError, parse_price


@runtime_checkable
class CatalogSource(Protocol):
    def fetch_products(self) -> Iterable[Product]:
        ...


@dataclass
class RawItem:
    label: str
    external_id: str
    variant_id: str | None
    name: str
    raw_price: str
    raw_ean: str
    raw_category: str
    currency: str


class BaseCatalogSource(ABC):
    SOURCE_NAME: str

    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        self.warnings: list[str] = []

    @abstractmethod
    def _iter_raw_items(self) -> Iterable[RawItem]:
        ...

    def fetch_products(self) -> list[Product]:
        seen_eans: dict[str, int] = {}
        products: list[Product] = []
        for item in self._iter_raw_items():
            product = self._normalize(item)
            if product is not None:
                self._append_with_dedup(products, seen_eans, item.label, product)
        return products

    def _normalize(self, item: RawItem) -> Product | None:
        name = item.name.strip()
        if not name:
            self.warnings.append(f"{item.label}: missing name, skipped")
            return None

        try:
            wholesale_price = parse_price(item.raw_price)
        except InvalidPriceError:
            self.warnings.append(f"{item.label}: invalid price '{item.raw_price}', skipped")
            return None

        if wholesale_price == 0:
            self.warnings.append(f"{item.label}: zero price, skipped")
            return None

        category = item.raw_category.strip() or "Bez kategorii"

        ean, ean_warning = normalize_ean(item.raw_ean)
        if ean_warning is not None:
            self.warnings.append(f"{item.label}: {ean_warning}")

        return Product(
            tenant_id=self.tenant_id,
            source=self.SOURCE_NAME,
            external_id=item.external_id,
            variant_id=item.variant_id,
            name=name,
            ean=ean,
            wholesale_price=wholesale_price,
            currency=item.currency,
            category=category,
        )

    def _append_with_dedup(
        self,
        products: list[Product],
        seen_eans: dict[str, int],
        label: str,
        product: Product,
    ) -> None:
        # Maps a seen EAN to its product's index in `products`, so a later
        # duplicate that turns out to be cheaper can overwrite the kept
        # product in place (preserving first-occurrence ordering) rather than
        # being appended as a second entry.
        if product.ean is not None and product.ean in seen_eans:
            existing_index = seen_eans[product.ean]
            existing = products[existing_index]
            if product.wholesale_price < existing.wholesale_price:
                self.warnings.append(
                    f"{label}: duplicate EAN '{product.ean}', replaced previously kept "
                    f"item (price {existing.wholesale_price}) with this cheaper item "
                    f"(price {product.wholesale_price})"
                )
                products[existing_index] = product
            else:
                self.warnings.append(
                    f"{label}: duplicate EAN '{product.ean}', dropped (price "
                    f"{product.wholesale_price} not cheaper than kept price "
                    f"{existing.wholesale_price})"
                )
            return

        products.append(product)
        if product.ean is not None:
            seen_eans[product.ean] = len(products) - 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/sources/test_base_source.py -v`
Expected: all 12 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/sources/base.py backend/tests/sources/test_base_source.py
git commit -m "Add BaseCatalogSource template method for shared normalization invariants"
```

Note: `CsvCatalogSource` and `ShopifyCatalogSource` are untouched by this task — they don't import
anything from `base.py` yet beyond the pre-existing `CatalogSource` Protocol, which is unchanged.
Run `cd backend && .venv/bin/pytest -v` once more here if you want early confirmation that adding
`BaseCatalogSource`/`RawItem` alongside the untouched `Protocol` caused no regression; it's not
required since Tasks 3 and 4 run the full suite anyway.

---

### Task 3: Migrate `CsvCatalogSource` to `BaseCatalogSource`

**Files:**
- Modify: `backend/app/sources/csv_source.py`
- Modify: `backend/tests/sources/test_csv_source.py`

**Interfaces:**
- Consumes: `BaseCatalogSource`, `RawItem` from Task 2.
- Produces: `CsvCatalogSource(BaseCatalogSource)` — same public constructor and `fetch_products()`
  behavior as before.

- [ ] **Step 1: Replace `csv_source.py`'s implementation**

Replace the full contents of `backend/app/sources/csv_source.py` with:

```python
from __future__ import annotations

import csv
import io
from typing import Iterable

from app.sources.base import BaseCatalogSource, RawItem
from app.sources.column_mapping import ColumnMapping, detect_column_mapping
from app.sources.csv_detect import detect_dialect, detect_encoding


class EmptyCsvError(Exception):
    pass


class CsvCatalogSource(BaseCatalogSource):
    SOURCE_NAME = "csv"

    def __init__(
        self,
        file_bytes: bytes,
        tenant_id: str,
        column_mapping: ColumnMapping | None = None,
        default_currency: str = "PLN",
    ) -> None:
        super().__init__(tenant_id)
        self.file_bytes = file_bytes
        self.column_mapping = column_mapping
        self.default_currency = default_currency

    def _iter_raw_items(self) -> Iterable[RawItem]:
        encoding = detect_encoding(self.file_bytes)
        text = self.file_bytes.decode(encoding)
        dialect = detect_dialect(text[:2048])
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)

        if reader.fieldnames is None:
            raise EmptyCsvError("CSV file has no header row")

        mapping = self.column_mapping or detect_column_mapping(list(reader.fieldnames))

        for row_index, row in enumerate(reader, start=2):
            raw_sku = (row.get(mapping.sku) or "").strip() if mapping.sku else ""
            external_id = raw_sku or str(row_index)

            yield RawItem(
                label=f"Row {row_index}",
                external_id=external_id,
                variant_id=None,
                name=row.get(mapping.name) or "",
                raw_price=row.get(mapping.wholesale_price) or "",
                raw_ean=row.get(mapping.ean) or "",
                raw_category=row.get(mapping.category) or "",
                currency=self.default_currency,
            )
```

- [ ] **Step 2: Trim `test_csv_source.py` to format-specific cases only**

Replace the full contents of `backend/tests/sources/test_csv_source.py` with:

```python
from decimal import Decimal

from app.sources.csv_source import CsvCatalogSource

VALID_EAN = "5901234123457"

HEADER = "Nazwa;Cena hurtowa;EAN;Kategoria\n"


def _csv(rows: str) -> bytes:
    return (HEADER + rows).encode("utf-8")


def test_parses_valid_row():
    source = CsvCatalogSource(_csv(f"Łóżko;100,00;{VALID_EAN};Meble\n"), tenant_id="t1")
    products = source.fetch_products()
    assert len(products) == 1
    product = products[0]
    assert product.name == "Łóżko"
    assert product.wholesale_price == Decimal("100.00")
    assert product.ean == VALID_EAN
    assert product.category == "Meble"
    assert product.tenant_id == "t1"
    assert product.source == "csv"
    assert product.currency == "PLN"


def test_parses_cp1250_encoded_file():
    raw = (HEADER + f"Łóżko;100,00;{VALID_EAN};Meble\n").encode("cp1250")
    source = CsvCatalogSource(raw, tenant_id="t1")
    products = source.fetch_products()
    assert products[0].name == "Łóżko"


def test_parses_comma_delimited_file():
    raw = f"Nazwa,Cena hurtowa,EAN,Kategoria\nŁóżko,100.00,{VALID_EAN},Meble\n".encode("utf-8")
    source = CsvCatalogSource(raw, tenant_id="t1")
    products = source.fetch_products()
    assert products[0].wholesale_price == Decimal("100.00")


def test_external_id_falls_back_to_row_index_without_sku_column():
    source = CsvCatalogSource(_csv(f"Łóżko;100,00;{VALID_EAN};Meble\n"), tenant_id="t1")
    products = source.fetch_products()
    assert len(products) == 1
    assert products[0].external_id == "2"


def test_external_id_uses_sku_column_when_present():
    header = "SKU;Nazwa;Cena hurtowa;EAN;Kategoria\n"
    row = f"ABC-123;Łóżko;100,00;{VALID_EAN};Meble\n"
    source = CsvCatalogSource((header + row).encode("utf-8"), tenant_id="t1")
    products = source.fetch_products()
    assert len(products) == 1
    assert products[0].external_id == "ABC-123"


def test_parses_bom_prefixed_csv_end_to_end():
    # b"\xef\xbb\xbf" is the UTF-8 BOM Excel-on-Windows prepends when exporting
    # CSV. Previously this raised ColumnMappingError because the BOM ended up
    # glued to the first header cell ("﻿Nazwa" matched no alias).
    raw = b"\xef\xbb\xbf" + _csv(f"Łóżko;100,00;{VALID_EAN};Meble\n")
    source = CsvCatalogSource(raw, tenant_id="t1")
    products = source.fetch_products()
    assert len(products) == 1
    assert products[0].name == "Łóżko"
```

- [ ] **Step 3: Run the full CSV test suite**

Run: `cd backend && .venv/bin/pytest tests/sources/test_csv_source.py tests/sources/test_csv_source_integration.py tests/sources/test_csv_preview.py -v`
Expected: all PASS. The removed invariant cases (missing name, zero/invalid price, dedup, UPC-A
padding, checksum, category fallback) are now covered by `test_base_source.py` from Task 2 — this
run only proves CSV-format parsing still works.

- [ ] **Step 4: Run the full backend suite as a regression check**

Run: `cd backend && .venv/bin/pytest -v`
Expected: all PASS, no failures anywhere else in the suite (nothing outside `app/sources/` imports
`CsvCatalogSource` in a way sensitive to this refactor — `orchestration.py` and `csv_preview.py`
only use its constructor and `fetch_products()`, both unchanged).

- [ ] **Step 5: Commit**

```bash
git add backend/app/sources/csv_source.py backend/tests/sources/test_csv_source.py
git commit -m "Migrate CsvCatalogSource onto BaseCatalogSource"
```

---

### Task 4: Migrate `ShopifyCatalogSource` to `BaseCatalogSource`

**Files:**
- Modify: `backend/app/sources/shopify_source.py`
- Modify: `backend/tests/sources/test_shopify_source.py`

**Interfaces:**
- Consumes: `BaseCatalogSource`, `RawItem` from Task 2.
- Produces: `ShopifyCatalogSource(BaseCatalogSource)` — same public constructor and
  `fetch_products()` behavior as before, except the sanctioned missing-name/-title change from the
  spec.

**Important subtlety to implement exactly as written below:** composing a variant's `name` as
`f"{title} - {variant_title}"` when `title` is blank but `variant_title` is not `"Default Title"`
would produce a non-blank string like `"- S"`, which would silently defeat
`BaseCatalogSource`'s missing-name check for every non-default variant of a blank-titled product.
The implementation below forces `name` to `""` whenever `title` is blank, regardless of
`variant_title`, so every variant of a blank-titled product is correctly skipped.

- [ ] **Step 1: Replace `shopify_source.py`'s implementation**

Replace the full contents of `backend/app/sources/shopify_source.py` with:

```python
from __future__ import annotations

import json
from typing import Any, Iterable

import httpx

from app.sources.base import BaseCatalogSource, RawItem

DEFAULT_API_VERSION = "2026-07"

CURRENCY_QUERY = "{ shop { currencyCode } }"


class ShopifyApiError(Exception):
    pass


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


class ShopifyCatalogSource(BaseCatalogSource):
    SOURCE_NAME = "shopify"

    def __init__(
        self,
        shop_domain: str,
        access_token: str,
        tenant_id: str,
        client: httpx.Client | None = None,
        api_version: str = DEFAULT_API_VERSION,
    ) -> None:
        super().__init__(tenant_id)
        self.shop_domain = shop_domain
        self.access_token = access_token
        self.api_version = api_version
        self._client = client or httpx.Client(timeout=30.0)

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
        except json.JSONDecodeError as exc:
            raise ShopifyApiError(f"Shopify response was not valid JSON: {exc}") from exc

        try:
            if "errors" in body:
                messages = "; ".join(e.get("message", str(e)) for e in body["errors"])
                raise ShopifyApiError(f"Shopify GraphQL error: {messages}")

            return body["data"]
        except (KeyError, AttributeError, TypeError) as exc:
            raise ShopifyApiError(f"Shopify response had an unexpected shape: {exc}") from exc

    def _iter_raw_items(self) -> Iterable[RawItem]:
        currency = self._post(CURRENCY_QUERY)["shop"]["currencyCode"]

        cursor: str | None = None
        while True:
            data = self._post(PRODUCTS_QUERY, {"cursor": cursor})["products"]
            for edge in data["edges"]:
                yield from self._map_product(edge["node"], currency)

            page_info = data["pageInfo"]
            if not page_info["hasNextPage"]:
                break

            next_cursor = page_info["endCursor"]
            if next_cursor == cursor:
                raise ShopifyApiError(
                    "Shopify pagination did not advance — endCursor did not change "
                    "across pages"
                )
            cursor = next_cursor

    def _map_product(self, node: dict[str, Any], currency: str) -> Iterable[RawItem]:
        product_id = node["id"]
        title = (node.get("title") or "").strip()
        category = node.get("productType") or ""

        for variant_edge in node["variants"]["edges"]:
            variant = variant_edge["node"]
            variant_id = variant["id"]
            variant_title = variant.get("title") or "Default Title"

            # A blank title composed with a non-default variant title would
            # still look non-blank (e.g. "- S"), silently defeating
            # BaseCatalogSource's missing-name check. Force it blank so every
            # variant of a blank-titled product is skipped, not just the
            # Default Title one.
            if not title:
                name = ""
            elif variant_title == "Default Title":
                name = title
            else:
                name = f"{title} - {variant_title}"

            yield RawItem(
                label=f"Product {product_id}, variant {variant_id}",
                external_id=product_id,
                variant_id=variant_id,
                name=name,
                raw_price=variant.get("price") or "",
                raw_ean=variant.get("barcode") or "",
                raw_category=category,
                currency=currency,
            )
```

- [ ] **Step 2: Update `test_shopify_source.py`**

Replace the full contents of `backend/tests/sources/test_shopify_source.py` with:

```python
import json
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


def test_skips_all_variants_of_product_with_blank_title():
    client = _FakeClient(
        currency="PLN",
        pages=[
            _single_product_page(
                {
                    "id": "gid://shopify/Product/7",
                    "title": "   ",
                    "productType": "Ogólne",
                    "variants": {
                        "edges": [
                            {
                                "node": {
                                    "id": "gid://shopify/ProductVariant/70",
                                    "title": "Default Title",
                                    "price": "10.00",
                                    "barcode": None,
                                }
                            },
                            {
                                "node": {
                                    "id": "gid://shopify/ProductVariant/71",
                                    "title": "S",
                                    "price": "12.00",
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

    assert products == []
    assert sum("missing name" in w for w in source.warnings) == 2
    assert any("ProductVariant/70" in w for w in source.warnings)
    assert any("ProductVariant/71" in w for w in source.warnings)


def test_raises_on_pagination_cursor_not_advancing():
    def _page(has_next: bool, cursor: str | None) -> dict:
        return {
            "edges": [
                {
                    "node": {
                        "id": "gid://shopify/Product/9",
                        "title": "Produkt",
                        "productType": "Ogólne",
                        "variants": {
                            "edges": [
                                {
                                    "node": {
                                        "id": "gid://shopify/ProductVariant/90",
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

    # First page legitimately advances the cursor to "cursor-1"; the second
    # page claims there is still more (hasNextPage: true) but repeats the
    # same endCursor — this must not loop forever.
    client = _FakeClient(
        currency="PLN",
        pages=[
            _page(True, "cursor-1"),
            _page(True, "cursor-1"),
        ],
    )
    source = _make_source(client)

    with pytest.raises(ShopifyApiError, match="did not advance"):
        source.fetch_products()


class _JsonDecodeErrorClient:
    """Simulates a 200 response whose body isn't valid JSON (e.g. an HTML
    error page)."""

    def post(self, *args, **kwargs):
        class _Resp:
            def raise_for_status(self) -> None:
                pass

            def json(self) -> dict:
                raise json.JSONDecodeError("Expecting value", "<html>", 0)

        return _Resp()


def test_raises_shopify_api_error_on_non_json_response():
    source = ShopifyCatalogSource(
        shop_domain="test-shop.myshopify.com",
        access_token="token",
        tenant_id="t1",
        client=_JsonDecodeErrorClient(),
    )

    with pytest.raises(ShopifyApiError):
        source.fetch_products()


class _MalformedErrorsShapeClient:
    """Simulates a GraphQL response where `errors` is present but not the
    expected list-of-dicts shape."""

    def post(self, url, headers, json):
        return _FakeResponse({"errors": "not a list"})


def test_raises_shopify_api_error_on_malformed_errors_shape():
    source = ShopifyCatalogSource(
        shop_domain="test-shop.myshopify.com",
        access_token="token",
        tenant_id="t1",
        client=_MalformedErrorsShapeClient(),
    )

    with pytest.raises(ShopifyApiError):
        source.fetch_products()
```

This removes 5 cases now covered generically by `test_base_source.py`
(`test_skips_zero_price_variant_and_falls_back_category`, `test_clears_invalid_barcode_checksum`,
`test_dedups_same_ean_across_variants_keeping_cheaper_price`, `test_pads_upc_a_barcode_to_ean_13`,
`test_strips_whitespace_only_product_type_before_fallback`) and replaces
`test_skips_product_with_blank_title` with `test_skips_all_variants_of_product_with_blank_title`,
which uses two variants (one `"Default Title"`, one not) specifically to prove the subtlety in
Step 1 is handled — this is the test that would have caught the `"- S"` bug if the fix above were
skipped.

- [ ] **Step 3: Run the Shopify test suite**

Run: `cd backend && .venv/bin/pytest tests/sources/test_shopify_source.py -v`
Expected: all 10 tests PASS.

- [ ] **Step 4: Run the full backend suite as a regression check**

Run: `cd backend && .venv/bin/pytest -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/sources/shopify_source.py backend/tests/sources/test_shopify_source.py
git commit -m "Migrate ShopifyCatalogSource onto BaseCatalogSource"
```

---

### Task 5: `add-catalog-source` skill + close out the repo-reviewer finding

**Files:**
- Create: `.claude/skills/add-catalog-source/SKILL.md`
- Modify: `.claude/agent-memory/repo-reviewer/source-protocol-invariants.md`
- Modify: `.claude/agent-memory/repo-reviewer/MEMORY.md`

**Interfaces:** none — documentation only, no code.

- [ ] **Step 1: Write the skill**

Create `.claude/skills/add-catalog-source/SKILL.md`:

```markdown
---
name: add-catalog-source
description: Use when adding a new CatalogSource implementation (e.g. WooCommerce, Allegro, a second Shopify-like platform) to IS_IT_WORTH_IT. Walks through subclassing BaseCatalogSource so the shared normalization invariants are inherited, never reimplemented.
---

# Add a catalog source

`app/sources/base.py` defines `BaseCatalogSource`, which owns `fetch_products()` end-to-end:
iterating raw items, normalizing each into a `Product`, and deduping by EAN. A new source
implements exactly one method — `_iter_raw_items()` — and gets five invariants for free:

1. Blank/missing name → skip, with a warning.
2. Zero or unparseable price → skip, with a warning (via `app.normalize.money.parse_price`).
3. Category: stripped, blank → `"Bez kategorii"`.
4. EAN: 12-digit numeric barcodes zero-padded to EAN-13, then checksum-validated; invalid → the
   field is cleared with a warning, the row is kept (via `app.normalize.ean.normalize_ean`).
5. EAN dedup across the whole fetch: on a repeated EAN, the cheaper item wins, with a warning
   either way.

**Do not reimplement any of these in the new source file.** This is exactly the gap that let the
Shopify sketch silently diverge before `BaseCatalogSource` existed (see
`.claude/agent-memory/repo-reviewer/source-protocol-invariants.md`) — a new source's only job is
mapping its own format into raw strings.

## Steps

1. **Create `app/sources/<name>_source.py`** with:

   ```python
   from app.sources.base import BaseCatalogSource, RawItem

   class <Name>CatalogSource(BaseCatalogSource):
       SOURCE_NAME = "<name>"

       def __init__(self, ..., tenant_id: str) -> None:
           super().__init__(tenant_id)
           ...

       def _iter_raw_items(self):
           for raw in ...:  # however this format is fetched/parsed
               yield RawItem(
                   label=...,           # identifies this item in warnings, e.g. "Row 5"
                   external_id=...,
                   variant_id=...,       # None if the format has no variant concept
                   name=...,             # raw, unstripped — do not blank-check here
                   raw_price=...,        # raw string — do not parse or zero-check here
                   raw_ean=...,          # raw barcode/EAN string — do not pad or validate here
                   raw_category=...,     # raw, unstripped — do not fallback here
                   currency=...,
               )
   ```

   Pass every field through **raw** — no `.strip()`, no price parsing, no EAN validation, no
   fallback logic. `BaseCatalogSource._normalize` owns all of that. The only mapping logic that
   belongs in `_iter_raw_items` is composing values the base class cannot know about — e.g.
   Shopify's `"{title} - {variant_title}"` variant naming (see `shopify_source.py` for a worked
   example, including the subtlety of what to do when the base name is itself blank).

2. **Give each `RawItem` a `label`** that identifies the row/item in warning messages. Follow the
   existing conventions: `"Row {n}"` for a row-oriented format, `"Product {id}, variant {id}"` for
   one with a product/variant split.

3. **Write format-specific tests only**, in `tests/sources/test_<name>_source.py`. The five shared
   invariants are already covered by `tests/sources/test_base_source.py` — do not re-test blank
   name, zero price, category fallback, EAN padding/checksum, or dedup per source. Test what is
   actually specific to this format: how raw records get parsed/fetched, field mapping
   correctness, pagination or chunking if applicable, and error handling for malformed responses.
   `tests/sources/test_csv_source.py` and `tests/sources/test_shopify_source.py` show the expected
   post-refactor scope.

4. **Wire the new source in** wherever it needs to be reachable (check
   `app/scans/orchestration.py` for how `CsvCatalogSource` is constructed and dispatched).

5. **Run the `repo-reviewer` subagent** before merging, per this project's whole-branch review
   convention (`CLAUDE.md`, "Whole-branch review").
```

- [ ] **Step 2: Update the repo-reviewer memory finding**

In `.claude/agent-memory/repo-reviewer/source-protocol-invariants.md`, replace the `## Stale when`
section (the last section of the file) with:

```markdown
## Stale when

**RESOLVED as of 2026-08-26.** `CatalogSource` is no longer a bare one-method `Protocol` that each
source reimplements against — `app/sources/base.py` now has `BaseCatalogSource`, a template-method
ABC that owns `fetch_products()` (normalization + dedup) entirely. Both `CsvCatalogSource` and
`ShopifyCatalogSource` implement only `_iter_raw_items()`; a new source (e.g. WooCommerce) cannot
omit any of the five invariants because it never gets to write the loop. The `add-catalog-source`
skill (`.claude/skills/add-catalog-source/SKILL.md`) walks through adding one correctly.

The detector below is no longer the right check for a *new* source — check whether it subclasses
`BaseCatalogSource` and implements nothing beyond `_iter_raw_items` instead. It remains useful only
as a regression check that `csv_source.py`/`shopify_source.py` haven't grown normalization logic
back:

```
grep -n 'strip()\|is_valid_ean\|len(raw\|seen_eans\|Bez kategorii' \
  backend/app/sources/csv_source.py backend/app/sources/shopify_source.py
```

Every match should be inside `BaseCatalogSource` in `base.py`, never in these two files.

Related: [[backend-data]], [[review-process]], [[backend-http-clients]].
```

- [ ] **Step 3: Update the MEMORY.md index line**

In `.claude/agent-memory/repo-reviewer/MEMORY.md`, replace:

```
- [CatalogSource's unwritten contract](source-protocol-invariants.md) — a 2nd source passes `isinstance()` + all tests while dropping dedup, UPC padding, name skip, category strip
```

with:

```
- [CatalogSource's unwritten contract — RESOLVED](source-protocol-invariants.md) — BaseCatalogSource now owns normalization+dedup; a 2nd source could no longer silently drop them
```

- [ ] **Step 4: Run the full backend suite one last time**

Run: `cd backend && .venv/bin/pytest -v`
Expected: all PASS.

- [ ] **Step 5: Verify the Definition of Done's grep check**

Run:
```bash
cd backend && grep -n 'strip()\|is_valid_ean\|len(raw\|seen_eans\|Bez kategorii' app/sources/csv_source.py app/sources/shopify_source.py
```
Expected: no output (empty).

- [ ] **Step 6: Commit**

```bash
git add .claude/skills/add-catalog-source/SKILL.md \
  .claude/agent-memory/repo-reviewer/source-protocol-invariants.md \
  .claude/agent-memory/repo-reviewer/MEMORY.md
git commit -m "Add add-catalog-source skill; close out source-protocol-invariants finding"
```

---

## After all tasks: whole-branch review

Per this project's `CLAUDE.md`, run the `repo-reviewer` subagent before merging this branch/phase —
per-task reviews passing is not sufficient here (`.claude/rules/planning.md`: Phase 5c shipped a
missing guard despite 7 clean per-task reviews).
