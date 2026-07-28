# Phase 0–2 Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the API-cost-free foundation of IS_IT_WORTH_IT: project scaffold, CSV catalog ingestion with normalization, and the margin calculation engine — all fully tested before a single Perplexity API call is ever made.

**Architecture:** Backend is a Python/FastAPI package (`backend/app/`) organized by responsibility (`models`, `sources`, `normalize`, `pricing`), each module small and independently testable. Frontend is a separate Vite/React/TS/Tailwind app (`frontend/`), scaffolded but not wired to backend logic yet — that's Phase 5. This plan covers Phase 0 (scaffold), Phase 1 (`CatalogSource` + normalize), and Phase 2 (margin engine) from the approved design spec.

**Tech Stack:** Python 3.11+, FastAPI, pytest, `decimal.Decimal` for all money. React 18+, Vite, TypeScript, Tailwind CSS v4 (`@tailwindcss/vite`).

## Global Constraints

- Money is always `decimal.Decimal`. Never `float` for prices, costs, or margins (spec §"Pieniądze na Decimal").
- Every backend module ships with a failing test first, then the minimal implementation (TDD, per workspace CLAUDE.md).
- Python dependency management: venv + `requirements.txt` at `backend/` root (workspace convention — no `pyproject.toml`/`uv` unless asked).
- **Git commits require explicit user approval per this project's workspace rule ("only commit when explicitly asked").** Each task below ends with a "stage & pause for confirmation" step instead of an automatic `git commit` — do not run `git commit` without the user confirming first, either per task or batched at a phase boundary.
- File layout inside `backend/app/`: `models/`, `sources/`, `normalize/`, `pricing/` — one clear responsibility per module, mirroring the design spec's pipeline stages.
- `CatalogSource` (Task 3) is a `Protocol`, not a base class — new sources (Shopify, Woo, later) implement it structurally, no inheritance required.

---

## Task 1: Backend scaffold (FastAPI + pytest)

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/pytest.ini`
- Create: `backend/app/__init__.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/test_main.py`

**Interfaces:**
- Produces: FastAPI app instance `app` importable as `from app.main import app`, with `GET /health` returning `{"status": "ok"}`.

- [ ] **Step 1: Create directory structure and venv**

```bash
mkdir -p backend/app backend/tests
python3 -m venv backend/.venv
```

- [ ] **Step 2: Write `backend/requirements.txt`**

```
fastapi>=0.115
uvicorn[standard]>=0.32
pytest>=8.3
httpx>=0.27
```

- [ ] **Step 3: Install dependencies**

```bash
backend/.venv/bin/pip install -r backend/requirements.txt
```

- [ ] **Step 4: Write `backend/pytest.ini`**

```ini
[pytest]
pythonpath = .
testpaths = tests
```

- [ ] **Step 5: Create empty package markers**

```bash
touch backend/app/__init__.py backend/tests/__init__.py
```

- [ ] **Step 6: Write the failing test — `backend/tests/test_main.py`**

```python
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 7: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 8: Write minimal implementation — `backend/app/main.py`**

```python
from fastapi import FastAPI

app = FastAPI(title="IS_IT_WORTH_IT")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 9: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_main.py -v`
Expected: PASS

- [ ] **Step 10: Manually verify the server starts**

```bash
cd backend && .venv/bin/uvicorn app.main:app --reload &
sleep 1
curl -s http://127.0.0.1:8000/health
kill %1
```

Expected output: `{"status":"ok"}`

- [ ] **Step 11: Stage changes and pause for commit confirmation**

```bash
git add backend/
```

Ask the user to confirm before running `git commit` (workspace rule — no auto-commit).

---

## Task 2: Frontend scaffold (Vite + React + TS + Tailwind v4)

**Files:**
- Create: `frontend/` (via `npm create vite@latest`)
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/src/index.css`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Produces: `npm run build` and `npm run lint` both exit 0 from `frontend/`.

- [ ] **Step 1: Scaffold the Vite project**

```bash
npm create vite@latest frontend -- --template react-ts
cd frontend && npm install
```

- [ ] **Step 2: Install Tailwind v4**

```bash
cd frontend && npm install tailwindcss @tailwindcss/vite
```

- [ ] **Step 3: Wire the Tailwind Vite plugin — `frontend/vite.config.ts`**

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
})
```

- [ ] **Step 4: Replace `frontend/src/index.css`**

```css
@import "tailwindcss";
```

- [ ] **Step 5: Replace `frontend/src/App.tsx` with a placeholder that proves Tailwind is wired**

```tsx
function App() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-100">
      <p className="text-lg font-medium">IS_IT_WORTH_IT — scaffold ready</p>
    </div>
  )
}

export default App
```

- [ ] **Step 6: Verify build succeeds**

Run: `cd frontend && npm run build`
Expected: exits 0, output contains `built in`

- [ ] **Step 7: Verify lint succeeds**

Run: `cd frontend && npm run lint`
Expected: exits 0, no errors printed

- [ ] **Step 8: Stage changes and pause for commit confirmation**

```bash
git add frontend/
```

Ask the user to confirm before running `git commit`.

---

## Task 3: Product model + CatalogSource protocol

**Files:**
- Create: `backend/app/models/__init__.py`
- Create: `backend/app/models/product.py`
- Create: `backend/app/sources/__init__.py`
- Create: `backend/app/sources/base.py`
- Test: `backend/tests/models/__init__.py`
- Test: `backend/tests/models/test_product.py`
- Test: `backend/tests/sources/__init__.py`
- Test: `backend/tests/sources/test_base.py`

**Interfaces:**
- Produces: `Product` frozen dataclass with fields `tenant_id: str, source: str, external_id: str, variant_id: str | None, name: str, ean: str | None, wholesale_price: Decimal, currency: str, category: str`.
- Produces: `CatalogSource` runtime-checkable `Protocol` with `fetch_products(self) -> Iterable[Product]`.
- Consumed by: Task 8 (`CsvCatalogSource` implements `CatalogSource` and returns `list[Product]`).

- [ ] **Step 1: Create directories**

```bash
mkdir -p backend/app/models backend/app/sources backend/tests/models backend/tests/sources
touch backend/app/models/__init__.py backend/app/sources/__init__.py
touch backend/tests/models/__init__.py backend/tests/sources/__init__.py
```

- [ ] **Step 2: Write the failing test — `backend/tests/models/test_product.py`**

```python
import dataclasses
from decimal import Decimal

import pytest

from app.models.product import Product


def _make_product(**overrides) -> Product:
    defaults = dict(
        tenant_id="t1",
        source="csv",
        external_id="1",
        variant_id=None,
        name="Test Product",
        ean=None,
        wholesale_price=Decimal("10.00"),
        currency="PLN",
        category="Test",
    )
    defaults.update(overrides)
    return Product(**defaults)


def test_product_holds_expected_fields():
    product = _make_product()
    assert product.name == "Test Product"
    assert product.wholesale_price == Decimal("10.00")


def test_product_is_immutable():
    product = _make_product()
    with pytest.raises(dataclasses.FrozenInstanceError):
        product.name = "Changed"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/models/test_product.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models.product'`

- [ ] **Step 4: Write minimal implementation — `backend/app/models/product.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Product:
    tenant_id: str
    source: str
    external_id: str
    variant_id: str | None
    name: str
    ean: str | None
    wholesale_price: Decimal
    currency: str
    category: str
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/models/test_product.py -v`
Expected: PASS

- [ ] **Step 6: Write the failing test — `backend/tests/sources/test_base.py`**

```python
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
```

- [ ] **Step 7: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/sources/test_base.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.sources.base'`

- [ ] **Step 8: Write minimal implementation — `backend/app/sources/base.py`**

```python
from __future__ import annotations

from typing import Iterable, Protocol, runtime_checkable

from app.models.product import Product


@runtime_checkable
class CatalogSource(Protocol):
    def fetch_products(self) -> Iterable[Product]:
        ...
```

- [ ] **Step 9: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/sources/test_base.py -v`
Expected: PASS

- [ ] **Step 10: Stage changes and pause for commit confirmation**

```bash
git add backend/app/models/ backend/app/sources/__init__.py backend/app/sources/base.py backend/tests/models/ backend/tests/sources/__init__.py backend/tests/sources/test_base.py
```

Ask the user to confirm before running `git commit`.

---

## Task 4: EAN-13/8 checksum validation

**Files:**
- Create: `backend/app/normalize/__init__.py`
- Create: `backend/app/normalize/ean.py`
- Test: `backend/tests/normalize/__init__.py`
- Test: `backend/tests/normalize/test_ean.py`

**Interfaces:**
- Produces: `is_valid_ean(code: str) -> bool`.
- Consumed by: Task 8 (`CsvCatalogSource` clears invalid EANs to `None`).

- [ ] **Step 1: Create directories**

```bash
mkdir -p backend/app/normalize backend/tests/normalize
touch backend/app/normalize/__init__.py backend/tests/normalize/__init__.py
```

- [ ] **Step 2: Write the failing test — `backend/tests/normalize/test_ean.py`**

```python
from app.normalize.ean import is_valid_ean


def test_valid_ean13_checksum():
    assert is_valid_ean("5901234123457") is True


def test_invalid_ean13_checksum():
    assert is_valid_ean("5901234123458") is False


def test_valid_ean8_checksum():
    assert is_valid_ean("40170725") is True


def test_invalid_ean8_checksum():
    assert is_valid_ean("40170724") is False


def test_non_digit_string_is_invalid():
    assert is_valid_ean("abcdefghijklm") is False


def test_wrong_length_is_invalid():
    assert is_valid_ean("123") is False
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/normalize/test_ean.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.normalize.ean'`

- [ ] **Step 4: Write minimal implementation — `backend/app/normalize/ean.py`**

```python
from __future__ import annotations


def is_valid_ean(code: str) -> bool:
    if not code.isdigit():
        return False

    if len(code) == 13:
        weights = [1, 3] * 6
        digits = [int(c) for c in code[:12]]
    elif len(code) == 8:
        weights = [3, 1, 3, 1, 3, 1, 3]
        digits = [int(c) for c in code[:7]]
    else:
        return False

    checksum = int(code[-1])
    total = sum(d * w for d, w in zip(digits, weights))
    calculated = (10 - (total % 10)) % 10
    return calculated == checksum
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/normalize/test_ean.py -v`
Expected: PASS (all 6 tests)

- [ ] **Step 6: Stage changes and pause for commit confirmation**

```bash
git add backend/app/normalize/__init__.py backend/app/normalize/ean.py backend/tests/normalize/__init__.py backend/tests/normalize/test_ean.py
```

Ask the user to confirm before running `git commit`.

---

## Task 5: Money parsing (`parse_price`)

**Files:**
- Create: `backend/app/normalize/money.py`
- Test: `backend/tests/normalize/test_money.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `parse_price(raw: str) -> Decimal`, `InvalidPriceError(Exception)`.
- Consumed by: Task 8 (`CsvCatalogSource` parses the wholesale price column).

- [ ] **Step 1: Write the failing test — `backend/tests/normalize/test_money.py`**

```python
from decimal import Decimal

import pytest

from app.normalize.money import InvalidPriceError, parse_price


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("12,50", Decimal("12.50")),
        ("12.50", Decimal("12.50")),
        ("12,50 zł", Decimal("12.50")),
        ("1 234,56", Decimal("1234.56")),
        ("10", Decimal("10")),
    ],
)
def test_parse_price_valid_inputs(raw, expected):
    assert parse_price(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "-5,00"])
def test_parse_price_rejects_invalid_inputs(raw):
    with pytest.raises(InvalidPriceError):
        parse_price(raw)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/normalize/test_money.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.normalize.money'`

- [ ] **Step 3: Write minimal implementation — `backend/app/normalize/money.py`**

```python
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_STRIP_PATTERN = re.compile(r"[^\d,.\-]")


class InvalidPriceError(Exception):
    pass


def parse_price(raw: str) -> Decimal:
    cleaned = _STRIP_PATTERN.sub("", raw.strip())
    if not cleaned:
        raise InvalidPriceError(raw)

    last_comma = cleaned.rfind(",")
    last_dot = cleaned.rfind(".")
    decimal_pos = max(last_comma, last_dot)

    if decimal_pos == -1:
        integer_part, decimal_part = cleaned, ""
    else:
        integer_part = cleaned[:decimal_pos]
        decimal_part = cleaned[decimal_pos + 1 :]

    integer_part = integer_part.replace(",", "").replace(".", "")

    if not integer_part.lstrip("-").isdigit() or (decimal_part and not decimal_part.isdigit()):
        raise InvalidPriceError(raw)

    normalized = f"{integer_part}.{decimal_part}" if decimal_part else integer_part

    try:
        value = Decimal(normalized)
    except InvalidOperation as exc:
        raise InvalidPriceError(raw) from exc

    if value < 0:
        raise InvalidPriceError(raw)

    return value
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/normalize/test_money.py -v`
Expected: PASS (8 parametrized cases)

- [ ] **Step 5: Stage changes and pause for commit confirmation**

```bash
git add backend/app/normalize/money.py backend/tests/normalize/test_money.py
```

Ask the user to confirm before running `git commit`.

---

## Task 6: Column mapping detection

**Files:**
- Create: `backend/app/sources/column_mapping.py`
- Test: `backend/tests/sources/test_column_mapping.py`

**Interfaces:**
- Produces: `ColumnMapping` frozen dataclass (`name: str, wholesale_price: str, ean: str, category: str`), `detect_column_mapping(header: list[str]) -> ColumnMapping`, `ColumnMappingError(Exception)`.
- Consumed by: Task 8 (`CsvCatalogSource` uses this when no explicit mapping is supplied).

- [ ] **Step 1: Write the failing test — `backend/tests/sources/test_column_mapping.py`**

```python
import pytest

from app.sources.column_mapping import ColumnMapping, ColumnMappingError, detect_column_mapping


def test_detects_polish_headers():
    mapping = detect_column_mapping(["Nazwa", "Cena hurtowa", "EAN", "Kategoria"])
    assert mapping == ColumnMapping(
        name="Nazwa", wholesale_price="Cena hurtowa", ean="EAN", category="Kategoria"
    )


def test_detects_english_headers_case_insensitively():
    mapping = detect_column_mapping(["name", "price", "ean", "category"])
    assert mapping == ColumnMapping(name="name", wholesale_price="price", ean="ean", category="category")


def test_raises_when_a_column_cannot_be_mapped():
    with pytest.raises(ColumnMappingError):
        detect_column_mapping(["Foo", "Bar"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/sources/test_column_mapping.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.sources.column_mapping'`

- [ ] **Step 3: Write minimal implementation — `backend/app/sources/column_mapping.py`**

```python
from __future__ import annotations

from dataclasses import dataclass

NAME_ALIASES = {"nazwa", "name", "produkt", "nazwa produktu", "product name", "product"}
PRICE_ALIASES = {"cena", "cena hurtowa", "price", "wholesale price", "cena netto", "cena zakupu"}
EAN_ALIASES = {"ean", "kod ean", "barcode", "kod kreskowy", "gtin"}
CATEGORY_ALIASES = {"kategoria", "category", "grupa", "grupa produktowa"}


class ColumnMappingError(Exception):
    pass


@dataclass(frozen=True)
class ColumnMapping:
    name: str
    wholesale_price: str
    ean: str
    category: str


def detect_column_mapping(header: list[str]) -> ColumnMapping:
    normalized = {h.strip().lower(): h for h in header}

    def find(aliases: set[str], field_label: str) -> str:
        for alias in aliases:
            if alias in normalized:
                return normalized[alias]
        raise ColumnMappingError(f"Could not detect column for '{field_label}' in header {header}")

    return ColumnMapping(
        name=find(NAME_ALIASES, "name"),
        wholesale_price=find(PRICE_ALIASES, "wholesale_price"),
        ean=find(EAN_ALIASES, "ean"),
        category=find(CATEGORY_ALIASES, "category"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/sources/test_column_mapping.py -v`
Expected: PASS

- [ ] **Step 5: Stage changes and pause for commit confirmation**

```bash
git add backend/app/sources/column_mapping.py backend/tests/sources/test_column_mapping.py
```

Ask the user to confirm before running `git commit`.

---

## Task 7: CSV encoding + dialect detection

**Files:**
- Create: `backend/app/sources/csv_detect.py`
- Test: `backend/tests/sources/test_csv_detect.py`

**Interfaces:**
- Produces: `detect_encoding(raw_bytes: bytes) -> str` (returns `"utf-8"` or `"cp1250"`), `detect_dialect(sample_text: str) -> csv.Dialect`.
- Consumed by: Task 8 (`CsvCatalogSource` uses both before parsing rows).

- [ ] **Step 1: Write the failing test — `backend/tests/sources/test_csv_detect.py`**

```python
import csv

from app.sources.csv_detect import detect_dialect, detect_encoding

SAMPLE_TEXT = "Nazwa;Cena;EAN;Kategoria\nŁóżko;100,00;5901234123457;Meble\n"


def test_detects_utf8_encoding():
    assert detect_encoding(SAMPLE_TEXT.encode("utf-8")) == "utf-8"


def test_falls_back_to_cp1250_when_utf8_decode_fails():
    assert detect_encoding(SAMPLE_TEXT.encode("cp1250")) == "cp1250"


def test_detects_semicolon_delimiter():
    dialect = detect_dialect(SAMPLE_TEXT)
    assert dialect.delimiter == ";"


def test_detects_comma_delimiter():
    comma_text = "Nazwa,Cena,EAN,Kategoria\nŁóżko,100.00,5901234123457,Meble\n"
    dialect = detect_dialect(comma_text)
    assert dialect.delimiter == ","


def test_falls_back_to_semicolon_when_sniffing_fails():
    dialect = detect_dialect("no delimiter characters at all")
    assert dialect.delimiter == ";"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/sources/test_csv_detect.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.sources.csv_detect'`

- [ ] **Step 3: Write minimal implementation — `backend/app/sources/csv_detect.py`**

```python
from __future__ import annotations

import csv


class _DefaultDialect(csv.Dialect):
    delimiter = ";"
    quotechar = '"'
    doublequote = True
    skipinitialspace = False
    lineterminator = "\r\n"
    quoting = csv.QUOTE_MINIMAL


def detect_encoding(raw_bytes: bytes) -> str:
    try:
        raw_bytes.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "cp1250"


def detect_dialect(sample_text: str) -> type[csv.Dialect]:
    try:
        return csv.Sniffer().sniff(sample_text, delimiters=";,")
    except csv.Error:
        return _DefaultDialect
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/sources/test_csv_detect.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Stage changes and pause for commit confirmation**

```bash
git add backend/app/sources/csv_detect.py backend/tests/sources/test_csv_detect.py
```

Ask the user to confirm before running `git commit`.

---

## Task 8: `CsvCatalogSource` — full row parsing

**Files:**
- Create: `backend/app/sources/csv_source.py`
- Test: `backend/tests/sources/test_csv_source.py`

**Interfaces:**
- Consumes: `Product` (Task 3), `is_valid_ean` (Task 4), `parse_price`/`InvalidPriceError` (Task 5), `ColumnMapping`/`detect_column_mapping` (Task 6), `detect_encoding`/`detect_dialect` (Task 7).
- Produces: `CsvCatalogSource` class implementing `CatalogSource`, with `__init__(self, file_bytes: bytes, tenant_id: str, column_mapping: ColumnMapping | None = None, default_currency: str = "PLN")`, `fetch_products(self) -> list[Product]`, and a `self.warnings: list[str]` attribute populated during parsing.
- Consumed by: Task 10 (integration smoke test), and later Phase 3/5 work.

- [ ] **Step 1: Write the failing test — `backend/tests/sources/test_csv_source.py`**

```python
from decimal import Decimal

from app.sources.csv_source import CsvCatalogSource

VALID_EAN = "5901234123457"
INVALID_EAN = "5901234123458"

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


def test_skips_row_with_missing_name():
    source = CsvCatalogSource(_csv(f";100,00;{VALID_EAN};Meble\n"), tenant_id="t1")
    products = source.fetch_products()
    assert len(products) == 0
    assert any("missing name" in w for w in source.warnings)


def test_skips_row_with_invalid_price():
    source = CsvCatalogSource(_csv(f"Łóżko;not-a-price;{VALID_EAN};Meble\n"), tenant_id="t1")
    products = source.fetch_products()
    assert len(products) == 0
    assert any("invalid price" in w for w in source.warnings)


def test_clears_ean_with_bad_checksum_but_keeps_row():
    source = CsvCatalogSource(_csv(f"Łóżko;100,00;{INVALID_EAN};Meble\n"), tenant_id="t1")
    products = source.fetch_products()
    assert len(products) == 1
    assert products[0].ean is None
    assert any("invalid EAN checksum" in w for w in source.warnings)


def test_skips_duplicate_ean():
    rows = f"Łóżko;100,00;{VALID_EAN};Meble\nStół;200,00;{VALID_EAN};Meble\n"
    source = CsvCatalogSource(_csv(rows), tenant_id="t1")
    products = source.fetch_products()
    assert len(products) == 1
    assert products[0].name == "Łóżko"
    assert any("duplicate EAN" in w for w in source.warnings)


def test_missing_category_defaults_to_uncategorized():
    source = CsvCatalogSource(_csv(f"Łóżko;100,00;{VALID_EAN};\n"), tenant_id="t1")
    products = source.fetch_products()
    assert products[0].category == "Bez kategorii"


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/sources/test_csv_source.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.sources.csv_source'`

- [ ] **Step 3: Write minimal implementation — `backend/app/sources/csv_source.py`**

```python
from __future__ import annotations

import csv
import io

from app.models.product import Product
from app.normalize.ean import is_valid_ean
from app.normalize.money import InvalidPriceError, parse_price
from app.sources.column_mapping import ColumnMapping, detect_column_mapping
from app.sources.csv_detect import detect_dialect, detect_encoding


class EmptyCsvError(Exception):
    pass


class CsvCatalogSource:
    SOURCE_NAME = "csv"

    def __init__(
        self,
        file_bytes: bytes,
        tenant_id: str,
        column_mapping: ColumnMapping | None = None,
        default_currency: str = "PLN",
    ) -> None:
        self.file_bytes = file_bytes
        self.tenant_id = tenant_id
        self.column_mapping = column_mapping
        self.default_currency = default_currency
        self.warnings: list[str] = []

    def fetch_products(self) -> list[Product]:
        encoding = detect_encoding(self.file_bytes)
        text = self.file_bytes.decode(encoding)
        dialect = detect_dialect(text[:2048])
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)

        if reader.fieldnames is None:
            raise EmptyCsvError("CSV file has no header row")

        mapping = self.column_mapping or detect_column_mapping(list(reader.fieldnames))

        seen_eans: set[str] = set()
        products: list[Product] = []

        for row_index, row in enumerate(reader, start=2):
            name = (row.get(mapping.name) or "").strip()
            if not name:
                self.warnings.append(f"Row {row_index}: missing name, skipped")
                continue

            raw_price = row.get(mapping.wholesale_price) or ""
            try:
                wholesale_price = parse_price(raw_price)
            except InvalidPriceError:
                self.warnings.append(f"Row {row_index}: invalid price '{raw_price}', skipped")
                continue

            category = (row.get(mapping.category) or "").strip() or "Bez kategorii"

            raw_ean = (row.get(mapping.ean) or "").strip()
            ean: str | None = None
            if raw_ean:
                if is_valid_ean(raw_ean):
                    ean = raw_ean
                else:
                    self.warnings.append(
                        f"Row {row_index}: invalid EAN checksum '{raw_ean}', ean cleared"
                    )

            if ean is not None:
                if ean in seen_eans:
                    self.warnings.append(f"Row {row_index}: duplicate EAN '{ean}', skipped")
                    continue
                seen_eans.add(ean)

            products.append(
                Product(
                    tenant_id=self.tenant_id,
                    source=self.SOURCE_NAME,
                    external_id=str(row_index),
                    variant_id=None,
                    name=name,
                    ean=ean,
                    wholesale_price=wholesale_price,
                    currency=self.default_currency,
                    category=category,
                )
            )

        return products
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/sources/test_csv_source.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Stage changes and pause for commit confirmation**

```bash
git add backend/app/sources/csv_source.py backend/tests/sources/test_csv_source.py
```

Ask the user to confirm before running `git commit`.

---

## Task 9: `group_by_category`

**Files:**
- Create: `backend/app/normalize/grouping.py`
- Test: `backend/tests/normalize/test_grouping.py`

**Interfaces:**
- Consumes: `Product` (Task 3).
- Produces: `group_by_category(products: Iterable[Product]) -> dict[str, list[Product]]`.
- Consumed by: Phase 3+ (scope/sampling logic groups by category before querying providers).

- [ ] **Step 1: Write the failing test — `backend/tests/normalize/test_grouping.py`**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/normalize/test_grouping.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.normalize.grouping'`

- [ ] **Step 3: Write minimal implementation — `backend/app/normalize/grouping.py`**

```python
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from app.models.product import Product


def group_by_category(products: Iterable[Product]) -> dict[str, list[Product]]:
    groups: dict[str, list[Product]] = defaultdict(list)
    for product in products:
        groups[product.category].append(product)
    return dict(groups)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/normalize/test_grouping.py -v`
Expected: PASS

- [ ] **Step 5: Stage changes and pause for commit confirmation**

```bash
git add backend/app/normalize/grouping.py backend/tests/normalize/test_grouping.py
```

Ask the user to confirm before running `git commit`.

---

## Task 10: Real-catalog integration smoke test

**Files:**
- Create: `backend/tests/sources/test_csv_source_integration.py`
- Modify: `.gitignore` (add real catalog fixture path)

**Interfaces:**
- Consumes: `CsvCatalogSource` (Task 8).
- Produces: nothing new — this is a verification-only task confirming Task 8 survives a real 6,500-row supplier file end to end.

This task needs the user's real ~6,500-row CSV file (mentioned during brainstorming as their standing test file). It is **not** committed to the repo — supplier catalogs are business-sensitive data. The test skips cleanly if the file isn't present, so the suite stays green in any environment.

- [ ] **Step 1: Add the fixture path to `.gitignore`**

Append to `backend/.gitignore` (create the file if it doesn't exist):

```
tests/fixtures/real_catalog.csv
```

- [ ] **Step 2: Ask the user for their real CSV file**

Ask where their ~6,500-row test CSV lives, then copy it to `backend/tests/fixtures/real_catalog.csv` (create the `fixtures/` directory first: `mkdir -p backend/tests/fixtures`).

- [ ] **Step 3: Write the integration test — `backend/tests/sources/test_csv_source_integration.py`**

```python
import os
from pathlib import Path

import pytest

from app.sources.csv_source import CsvCatalogSource

REAL_CATALOG_PATH = Path(
    os.environ.get("IS_IT_WORTH_IT_SAMPLE_CSV", "tests/fixtures/real_catalog.csv")
)


@pytest.mark.skipif(
    not REAL_CATALOG_PATH.exists(),
    reason=(
        f"Real catalog fixture not found at {REAL_CATALOG_PATH}; "
        "set IS_IT_WORTH_IT_SAMPLE_CSV or place the file there to run this test"
    ),
)
def test_parses_real_catalog_without_crashing():
    file_bytes = REAL_CATALOG_PATH.read_bytes()
    source = CsvCatalogSource(file_bytes=file_bytes, tenant_id="test-tenant")

    products = source.fetch_products()

    assert len(products) > 0
    assert all(p.wholesale_price >= 0 for p in products)
    print(f"Parsed {len(products)} products, {len(source.warnings)} warnings")
```

- [ ] **Step 4: Run the test with output visible**

Run: `cd backend && .venv/bin/pytest tests/sources/test_csv_source_integration.py -v -s`
Expected: PASS, with a printed line like `Parsed 6500 products, N warnings`. If it fails, the failure points at a real edge case in the supplier file — fix `CsvCatalogSource` (Task 8) to handle it, don't special-case around it.

- [ ] **Step 5: Run the full test suite to confirm nothing regressed**

Run: `cd backend && .venv/bin/pytest -v`
Expected: all tests PASS (the integration test PASSes if the fixture was added, SKIPs otherwise — both are acceptable).

- [ ] **Step 6: Stage changes and pause for commit confirmation**

```bash
git add backend/.gitignore backend/tests/sources/test_csv_source_integration.py
```

Note: do **not** `git add` the real CSV fixture itself — it's gitignored on purpose. Ask the user to confirm before running `git commit`.

---

## Task 11: `CostConfig`, `MarginResult`, rounding helpers

**Files:**
- Create: `backend/app/pricing/__init__.py`
- Create: `backend/app/pricing/margin.py`
- Test: `backend/tests/pricing/__init__.py`
- Test: `backend/tests/pricing/test_rounding.py`

**Interfaces:**
- Produces: `round_money(value: Decimal) -> Decimal` (2dp, `ROUND_HALF_UP`), `round_pct(value: Decimal) -> Decimal` (4dp, `ROUND_HALF_UP`), `CostConfig` frozen dataclass (`commission_pct, shipping_cost, vat_pct, returns_pct: Decimal`), `MarginResult` frozen dataclass (`scenario_pct, sale_price, net_revenue, total_costs, margin, margin_pct: Decimal`).
- Consumed by: Task 12, Task 13.

- [ ] **Step 1: Create directories**

```bash
mkdir -p backend/app/pricing backend/tests/pricing
touch backend/app/pricing/__init__.py backend/tests/pricing/__init__.py
```

- [ ] **Step 2: Write the failing test — `backend/tests/pricing/test_rounding.py`**

```python
from decimal import Decimal

from app.pricing.margin import round_money, round_pct


def test_round_money_rounds_half_up_to_two_places():
    assert round_money(Decimal("81.300813008")) == Decimal("81.30")
    assert round_money(Decimal("-5.699186991")) == Decimal("-5.70")


def test_round_pct_rounds_half_up_to_four_places():
    assert round_pct(Decimal("-0.05699186991")) == Decimal("-0.0570")
    assert round_pct(Decimal("0.14300813008")) == Decimal("0.1430")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/pricing/test_rounding.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.pricing.margin'`

- [ ] **Step 4: Write minimal implementation — `backend/app/pricing/margin.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


def round_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round_pct(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class CostConfig:
    commission_pct: Decimal
    shipping_cost: Decimal
    vat_pct: Decimal
    returns_pct: Decimal


@dataclass(frozen=True)
class MarginResult:
    scenario_pct: Decimal
    sale_price: Decimal
    net_revenue: Decimal
    total_costs: Decimal
    margin: Decimal
    margin_pct: Decimal
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/pricing/test_rounding.py -v`
Expected: PASS

- [ ] **Step 6: Stage changes and pause for commit confirmation**

```bash
git add backend/app/pricing/__init__.py backend/app/pricing/margin.py backend/tests/pricing/__init__.py backend/tests/pricing/test_rounding.py
```

Ask the user to confirm before running `git commit`.

---

## Task 12: `calculate_margin` (single scenario)

**Files:**
- Modify: `backend/app/pricing/margin.py`
- Test: `backend/tests/pricing/test_margin.py`

**Interfaces:**
- Consumes: `CostConfig`, `MarginResult`, `round_money`, `round_pct` (Task 11).
- Produces: `calculate_margin(wholesale_price: Decimal, market_price: Decimal, cost_config: CostConfig, scenario_pct: Decimal) -> MarginResult`.
- Consumed by: Task 13.

Cost model (spec's "model B"): `sale_price = market_price * (1 + scenario_pct)`. VAT-inclusive sale price, so `net_revenue = sale_price / (1 + vat_pct)`. Commission and returns are taken as a percentage of the gross sale price. `total_costs = wholesale_price + shipping_cost + commission_amount + returns_amount`. `margin = net_revenue - total_costs`. `margin_pct = margin / sale_price`.

- [ ] **Step 1: Write the failing test — `backend/tests/pricing/test_margin.py`**

```python
from decimal import Decimal

from app.pricing.margin import CostConfig, calculate_margin

COST_CONFIG = CostConfig(
    commission_pct=Decimal("0.10"),
    shipping_cost=Decimal("15.00"),
    vat_pct=Decimal("0.23"),
    returns_pct=Decimal("0.02"),
)


def test_unprofitable_at_market_price():
    result = calculate_margin(
        wholesale_price=Decimal("60.00"),
        market_price=Decimal("100.00"),
        cost_config=COST_CONFIG,
        scenario_pct=Decimal("0.00"),
    )
    assert result.sale_price == Decimal("100.00")
    assert result.net_revenue == Decimal("81.30")
    assert result.total_costs == Decimal("87.00")
    assert result.margin == Decimal("-5.70")
    assert result.margin_pct == Decimal("-0.0570")


def test_unprofitable_even_5pct_above_market():
    result = calculate_margin(
        wholesale_price=Decimal("60.00"),
        market_price=Decimal("100.00"),
        cost_config=COST_CONFIG,
        scenario_pct=Decimal("0.05"),
    )
    assert result.sale_price == Decimal("105.00")
    assert result.margin == Decimal("-2.23")
    assert result.margin_pct == Decimal("-0.0213")


def test_profitable_at_market_price():
    result = calculate_margin(
        wholesale_price=Decimal("40.00"),
        market_price=Decimal("100.00"),
        cost_config=COST_CONFIG,
        scenario_pct=Decimal("0.00"),
    )
    assert result.sale_price == Decimal("100.00")
    assert result.net_revenue == Decimal("81.30")
    assert result.total_costs == Decimal("67.00")
    assert result.margin == Decimal("14.30")
    assert result.margin_pct == Decimal("0.1430")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/pricing/test_margin.py -v`
Expected: FAIL with `ImportError: cannot import name 'calculate_margin'`

- [ ] **Step 3: Add `calculate_margin` to `backend/app/pricing/margin.py`**

Append to the existing file (after the `MarginResult` dataclass):

```python
def calculate_margin(
    wholesale_price: Decimal,
    market_price: Decimal,
    cost_config: CostConfig,
    scenario_pct: Decimal,
) -> MarginResult:
    sale_price = market_price * (Decimal("1") + scenario_pct)
    net_revenue = sale_price / (Decimal("1") + cost_config.vat_pct)
    commission_amount = sale_price * cost_config.commission_pct
    returns_amount = sale_price * cost_config.returns_pct
    total_costs = wholesale_price + cost_config.shipping_cost + commission_amount + returns_amount
    margin = net_revenue - total_costs
    margin_pct = margin / sale_price

    return MarginResult(
        scenario_pct=scenario_pct,
        sale_price=round_money(sale_price),
        net_revenue=round_money(net_revenue),
        total_costs=round_money(total_costs),
        margin=round_money(margin),
        margin_pct=round_pct(margin_pct),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/pricing/test_margin.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Stage changes and pause for commit confirmation**

```bash
git add backend/app/pricing/margin.py backend/tests/pricing/test_margin.py
```

Ask the user to confirm before running `git commit`.

---

## Task 13: `calculate_margin_matrix` (scenario widełki)

**Files:**
- Modify: `backend/app/pricing/margin.py`
- Test: `backend/tests/pricing/test_margin_matrix.py`

**Interfaces:**
- Consumes: `CostConfig`, `MarginResult`, `calculate_margin` (Task 12).
- Produces: `SCENARIO_ADJUSTMENTS: tuple[Decimal, ...]` = `(-0.10, -0.05, 0.00, 0.05)`, `calculate_margin_matrix(wholesale_price: Decimal, market_price: Decimal, cost_config: CostConfig, scenarios: tuple[Decimal, ...] = SCENARIO_ADJUSTMENTS) -> list[MarginResult]`.
- Consumed by: Phase 3+ report aggregation (not in this plan).

- [ ] **Step 1: Write the failing test — `backend/tests/pricing/test_margin_matrix.py`**

```python
from decimal import Decimal

from app.pricing.margin import CostConfig, calculate_margin_matrix

COST_CONFIG = CostConfig(
    commission_pct=Decimal("0.10"),
    shipping_cost=Decimal("15.00"),
    vat_pct=Decimal("0.23"),
    returns_pct=Decimal("0.02"),
)


def test_matrix_returns_four_scenarios_in_order():
    results = calculate_margin_matrix(
        wholesale_price=Decimal("40.00"),
        market_price=Decimal("100.00"),
        cost_config=COST_CONFIG,
    )

    assert [r.scenario_pct for r in results] == [
        Decimal("-0.10"),
        Decimal("-0.05"),
        Decimal("0.00"),
        Decimal("0.05"),
    ]
    assert [r.sale_price for r in results] == [
        Decimal("90.00"),
        Decimal("95.00"),
        Decimal("100.00"),
        Decimal("105.00"),
    ]
    assert [r.margin for r in results] == [
        Decimal("7.37"),
        Decimal("10.84"),
        Decimal("14.30"),
        Decimal("17.77"),
    ]
    assert [r.margin_pct for r in results] == [
        Decimal("0.0819"),
        Decimal("0.1141"),
        Decimal("0.1430"),
        Decimal("0.1692"),
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/pricing/test_margin_matrix.py -v`
Expected: FAIL with `ImportError: cannot import name 'calculate_margin_matrix'`

- [ ] **Step 3: Add `SCENARIO_ADJUSTMENTS` and `calculate_margin_matrix` to `backend/app/pricing/margin.py`**

Append to the existing file:

```python
SCENARIO_ADJUSTMENTS: tuple[Decimal, ...] = (
    Decimal("-0.10"),
    Decimal("-0.05"),
    Decimal("0.00"),
    Decimal("0.05"),
)


def calculate_margin_matrix(
    wholesale_price: Decimal,
    market_price: Decimal,
    cost_config: CostConfig,
    scenarios: tuple[Decimal, ...] = SCENARIO_ADJUSTMENTS,
) -> list[MarginResult]:
    return [
        calculate_margin(wholesale_price, market_price, cost_config, scenario_pct)
        for scenario_pct in scenarios
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/pricing/test_margin_matrix.py -v`
Expected: PASS

- [ ] **Step 5: Run the full backend test suite**

Run: `cd backend && .venv/bin/pytest -v`
Expected: all tests PASS (Tasks 1, 3–9, 11–13 combined; Task 10's integration test PASSes or SKIPs depending on fixture presence).

- [ ] **Step 6: Stage changes and pause for commit confirmation**

```bash
git add backend/app/pricing/margin.py backend/tests/pricing/test_margin_matrix.py
```

Ask the user to confirm before running `git commit`.

---

## Plan-level verification (matches spec's Phase 0–2 checkpoints)

1. `cd backend && .venv/bin/pytest -v` — all green (Task 10's real-catalog test passes or skips, never fails silently).
2. `cd frontend && npm run build && npm run lint` — both exit 0.
3. `cd backend && .venv/bin/uvicorn app.main:app --reload` then `curl http://127.0.0.1:8000/health` — returns `{"status":"ok"}`.
4. Every money value touched by `parse_price`, `round_money`, `round_pct`, `calculate_margin` is a `Decimal` — `grep -rn "float(" backend/app/` should return nothing in `normalize/` or `pricing/`.
5. `CsvCatalogSource` and `CatalogSource` are structurally decoupled from CSV specifics in `Product`/`CatalogSource` (Task 3) — confirms the Phase 6 `ShopifySource` can implement the same protocol without touching `models/` or `pricing/`.
