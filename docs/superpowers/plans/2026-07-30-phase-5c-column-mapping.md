# Phase 5c — Column-Mapping Correction Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Insert a column-mapping correction screen (`Upload → Mapping → Scope+Estimate → Progress
→ Report`) so a user can see and fix how the CSV's columns map to name/wholesale price/EAN/category
before any scan is created — closing the deliberate deferral from Phase 4.

**Architecture:** A new backend `build_csv_preview` function reuses `CsvCatalogSource.fetch_products()`
verbatim (the same code that already powers `POST /scans`) to produce a live, real parse of the
uploaded file against whatever mapping is currently known — auto-detected, user-overridden, or a mix
— without persisting anything. `POST /scans` gains the same mapping fields so the confirmed choice
carries straight into the real scan. On the frontend, a new `MappingStep` sits between `UploadStep`
and `ScopeEstimateStep`, calling the preview endpoint on mount and again on an explicit "Odśwież
podgląd" click — never on every dropdown change, matching the explicit-recompute pattern already
established by `ScopeEstimateStep`'s "Oszacuj koszt" and `ReportStep`'s "Przelicz".

**Tech Stack:** FastAPI + `Decimal`-only money math (backend, unchanged from prior phases) — this
phase touches no money math directly. React 19 + TypeScript + Tailwind (frontend, matching Phases
5a/5b). No new dependencies anywhere in this plan.

## Global Constraints

- Auto-detection failure is never an error at preview time. A field that can't be resolved becomes
  `null` in the response; the frontend renders it as an empty dropdown the user must fill manually.
  The existing, raising `detect_column_mapping` is untouched — still used by direct `POST /scans`
  callers that supply no mapping at all.
- The preview endpoint always runs a full parse (via `CsvCatalogSource.fetch_products()`) against
  whatever mapping is currently resolved, returning real counts/warnings — refreshed only on an
  explicit action, never per-keystroke.
- The confirmed mapping reaches `POST /scans` by re-sending the same `File` object a second time
  (already held in wizard state) with the mapping as extra form fields — no server-side file
  staging/session.
- Sample rows are raw CSV rows (all original columns, not just the 4 mapped fields), capped at 10.
  Warnings capped at 20 with a `warning_count` total.
- `POST /scans` and `POST /csv/preview` share one validation rule: either all four of
  `name_column`/`wholesale_price_column`/`ean_column`/`category_column` are supplied together, or
  none are — a partial subset is rejected with 400. `sku_column` may be supplied independently.
- Visual direction: no new design pass — continues Phase 5b's `ReportStep` system exactly:
  `slate-950`/`emerald-600` palette, `rounded-2xl` grouped-card for the mapping fields, hairline
  table for the sample-rows preview, explicit-action buttons instead of live recompute.
- Design spec: `docs/superpowers/specs/2026-07-30-phase-5c-column-mapping-design.md`. Read it if any
  task description here feels ambiguous.

---

## File Structure

- Modify: `backend/app/sources/column_mapping.py` — `ColumnMapping`'s 4 required fields become
  `str | None`; new `detect_column_mapping_partial`.
- Modify: `backend/tests/sources/test_column_mapping.py` — append tests for the new function.
- Create: `backend/app/sources/csv_preview.py` — `CsvPreview`, `build_csv_preview`.
- Create: `backend/tests/sources/test_csv_preview.py`.
- Modify: `backend/app/scans/api.py` — new `POST /csv/preview` endpoint, shared
  `_column_mapping_from_form` helper, `POST /scans` gains the same 5 form fields.
- Modify: `backend/app/scans/orchestration.py` — `create_scan` gains an optional `column_mapping`
  parameter, threaded into `CsvCatalogSource`.
- Modify: `backend/tests/scans/test_api.py` — append tests for `/csv/preview` and the mapping-aware
  `POST /scans`.
- Modify: `frontend/src/api/types.ts` — add `ColumnMapping`, `CsvPreview`.
- Modify: `frontend/src/api/client.ts` — add `getCsvPreview`; `createScan` gains an optional
  `columnMapping` parameter; new shared `appendColumnMapping` helper.
- Modify: `frontend/src/api/client.test.ts` — append tests for both.
- Modify: `frontend/vite.config.ts` — add `/csv` to the dev-server proxy.
- Create: `frontend/src/steps/MappingStep.tsx`.
- Create: `frontend/src/steps/MappingStep.test.tsx`.
- Modify: `frontend/src/App.tsx` — insert the `'mapping'` wizard step.
- Modify: `frontend/src/App.test.tsx` — both existing walkthrough tests now pass through
  `MappingStep`.
- Modify: `frontend/src/steps/ScopeEstimateStep.tsx` — gains a required `columnMapping` prop, passed
  to `createScan`.
- Modify: `frontend/src/steps/ScopeEstimateStep.test.tsx` — all 7 `render(<ScopeEstimateStep .../>)`
  calls gain the new required prop.

---

## Task 1: `ColumnMapping` becomes partial-friendly + `detect_column_mapping_partial`

**Files:**
- Modify: `backend/app/sources/column_mapping.py`
- Modify: `backend/tests/sources/test_column_mapping.py`

**Interfaces:**
- Produces: `ColumnMapping` (frozen dataclass, now `name: str | None`, `wholesale_price: str | None`,
  `ean: str | None`, `category: str | None`, `sku: str | None = None` — `sku` unchanged, the other
  four widened from `str`), `detect_column_mapping_partial(header: list[str]) -> ColumnMapping` (never
  raises; an unresolved required field is `None`). The existing, raising `detect_column_mapping` is
  unchanged. Used by Task 2's `build_csv_preview` and Task 3's API layer.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/sources/test_column_mapping.py` (it already imports `ColumnMapping`,
`ColumnMappingError`, `detect_column_mapping` at the top — add `detect_column_mapping_partial` to
that import):

```python
def test_partial_detection_returns_none_for_missing_required_fields():
    mapping = detect_column_mapping_partial(["Nazwa", "Kategoria"])
    assert mapping == ColumnMapping(name="Nazwa", wholesale_price=None, ean=None, category="Kategoria")


def test_partial_detection_never_raises_when_nothing_matches():
    mapping = detect_column_mapping_partial(["Foo", "Bar"])
    assert mapping == ColumnMapping(name=None, wholesale_price=None, ean=None, category=None)


def test_partial_detection_matches_everything_when_fully_detectable():
    mapping = detect_column_mapping_partial(["Nazwa", "Cena hurtowa", "EAN", "Kategoria"])
    assert mapping == ColumnMapping(
        name="Nazwa", wholesale_price="Cena hurtowa", ean="EAN", category="Kategoria"
    )


def test_partial_detection_detects_sku_the_same_way_as_full_detection():
    mapping = detect_column_mapping_partial(["SKU", "ean", "nazwa", "kategoria", "cena"])
    assert mapping.sku == "SKU"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/sources/test_column_mapping.py -v -k partial`
Expected: FAIL with `ImportError: cannot import name 'detect_column_mapping_partial'`

- [ ] **Step 3: Write minimal implementation**

In `backend/app/sources/column_mapping.py`, change the `ColumnMapping` dataclass:

```python
@dataclass(frozen=True)
class ColumnMapping:
    name: str | None
    wholesale_price: str | None
    ean: str | None
    category: str | None
    sku: str | None = None
```

Add this new function after the existing `detect_column_mapping` (which stays exactly as-is —
still raising `ColumnMappingError` for any direct caller that supplies no mapping override):

```python
def detect_column_mapping_partial(header: list[str]) -> ColumnMapping:
    """Like detect_column_mapping, but never raises — an unresolved required
    field becomes None instead of raising ColumnMappingError, so the caller
    can surface it as "pick manually" instead of failing outright."""
    normalized = {h.strip().lower(): h for h in header}

    def find_optional(aliases: tuple[str, ...]) -> str | None:
        for alias in aliases:
            if alias in normalized:
                return normalized[alias]
        return None

    return ColumnMapping(
        name=find_optional(NAME_ALIASES),
        wholesale_price=find_optional(PRICE_ALIASES),
        ean=find_optional(EAN_ALIASES),
        category=find_optional(CATEGORY_ALIASES),
        sku=find_optional(SKU_ALIASES),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/sources/test_column_mapping.py -v`
Expected: PASS (all tests in the file, including the 4 new ones)

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && .venv/bin/python -m pytest`
Expected: all pass (widening the 4 fields to `str | None` is a supertype change — every existing
construction of `ColumnMapping` with plain `str` values remains valid).

- [ ] **Step 6: Commit**

```bash
git add backend/app/sources/column_mapping.py backend/tests/sources/test_column_mapping.py
git commit -m "Make ColumnMapping's required fields optional; add detect_column_mapping_partial"
```

---

## Task 2: `build_csv_preview` — reuse `CsvCatalogSource.fetch_products()` for a live, non-persisting parse

**Files:**
- Create: `backend/app/sources/csv_preview.py`
- Create: `backend/tests/sources/test_csv_preview.py`

**Interfaces:**
- Consumes: `ColumnMapping`, `detect_column_mapping_partial` from Task 1's
  `app.sources.column_mapping`; `CsvCatalogSource`, `EmptyCsvError` from `app.sources.csv_source`
  (existing); `detect_dialect`, `detect_encoding` from `app.sources.csv_detect` (existing).
- Produces: `CsvPreview` (frozen dataclass: `headers: list[str]`, `mapping: ColumnMapping`,
  `sample_rows: list[dict[str, str]]`, `total_rows: int`, `parsed_count: int`, `warnings: list[str]`,
  `warning_count: int`), `build_csv_preview(csv_bytes: bytes, tenant_id: str, mapping_override:
  ColumnMapping | None) -> CsvPreview`. Raises `EmptyCsvError` if the file has no header row at all.
  Used by Task 3's `POST /csv/preview` endpoint.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/sources/test_csv_preview.py
import pytest

from app.sources.column_mapping import ColumnMapping
from app.sources.csv_preview import build_csv_preview
from app.sources.csv_source import EmptyCsvError

CSV_BYTES = (
    "nazwa;cena;ean;kategoria\n"
    "Produkt A;10,00;5901234123457;Elektronika\n"
    "Produkt B;abc;;Dom\n"
).encode("utf-8")


def test_build_preview_with_full_auto_detection():
    preview = build_csv_preview(CSV_BYTES, tenant_id="t1", mapping_override=None)

    assert preview.headers == ["nazwa", "cena", "ean", "kategoria"]
    assert preview.mapping == ColumnMapping(
        name="nazwa", wholesale_price="cena", ean="ean", category="kategoria"
    )
    assert preview.total_rows == 2
    assert preview.parsed_count == 1
    assert len(preview.warnings) == 1
    assert preview.warning_count == 1
    assert preview.sample_rows[0]["nazwa"] == "Produkt A"


def test_build_preview_with_partial_override():
    # ean is explicitly given (even though it would auto-detect the same way here);
    # the rest are left None and fall back to auto-detection.
    override = ColumnMapping(name=None, wholesale_price=None, ean="ean", category=None)

    preview = build_csv_preview(CSV_BYTES, tenant_id="t1", mapping_override=override)

    assert preview.mapping == ColumnMapping(
        name="nazwa", wholesale_price="cena", ean="ean", category="kategoria"
    )


def test_build_preview_when_required_field_cannot_be_resolved():
    csv_bytes = ("nazwa;kategoria\nProdukt A;Elektronika\n").encode("utf-8")

    preview = build_csv_preview(csv_bytes, tenant_id="t1", mapping_override=None)

    assert preview.mapping == ColumnMapping(
        name="nazwa", wholesale_price=None, ean=None, category="kategoria"
    )
    assert preview.parsed_count == 0
    assert preview.warnings == []
    assert preview.warning_count == 0
    assert preview.headers == ["nazwa", "kategoria"]
    assert preview.sample_rows[0]["nazwa"] == "Produkt A"


def test_build_preview_raises_empty_csv_error_for_missing_header():
    with pytest.raises(EmptyCsvError):
        build_csv_preview(b"", tenant_id="t1", mapping_override=None)


def test_build_preview_caps_sample_rows_and_warnings():
    header = "nazwa;cena;ean;kategoria\n"
    rows = "".join(f"Produkt {i};abc;;Dom\n" for i in range(30))
    csv_bytes = (header + rows).encode("utf-8")

    preview = build_csv_preview(csv_bytes, tenant_id="t1", mapping_override=None)

    assert preview.total_rows == 30
    assert len(preview.sample_rows) == 10
    assert len(preview.warnings) == 20
    assert preview.warning_count == 30
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/sources/test_csv_preview.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.sources.csv_preview'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/sources/csv_preview.py
from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from app.sources.column_mapping import ColumnMapping, detect_column_mapping_partial
from app.sources.csv_detect import detect_dialect, detect_encoding
from app.sources.csv_source import CsvCatalogSource, EmptyCsvError

SAMPLE_ROW_LIMIT = 10
WARNING_LIMIT = 20


@dataclass(frozen=True)
class CsvPreview:
    headers: list[str]
    mapping: ColumnMapping
    sample_rows: list[dict[str, str]]
    total_rows: int
    parsed_count: int
    warnings: list[str]
    warning_count: int


def _merge_mapping(override: ColumnMapping | None, detected: ColumnMapping) -> ColumnMapping:
    if override is None:
        return detected
    return ColumnMapping(
        name=override.name or detected.name,
        wholesale_price=override.wholesale_price or detected.wholesale_price,
        ean=override.ean or detected.ean,
        category=override.category or detected.category,
        sku=override.sku or detected.sku,
    )


def build_csv_preview(
    csv_bytes: bytes, tenant_id: str, mapping_override: ColumnMapping | None
) -> CsvPreview:
    encoding = detect_encoding(csv_bytes)
    text = csv_bytes.decode(encoding)
    dialect = detect_dialect(text[:2048])
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)

    if reader.fieldnames is None:
        raise EmptyCsvError("CSV file has no header row")

    headers = list(reader.fieldnames)
    rows = list(reader)

    mapping = _merge_mapping(mapping_override, detect_column_mapping_partial(headers))

    sample_rows = [
        {k: (v if v is not None else "") for k, v in row.items()}
        for row in rows[:SAMPLE_ROW_LIMIT]
    ]
    total_rows = len(rows)

    parsed_count = 0
    warnings: list[str] = []
    if mapping.name and mapping.wholesale_price and mapping.ean and mapping.category:
        source = CsvCatalogSource(csv_bytes, tenant_id=tenant_id, column_mapping=mapping)
        parsed_count = len(source.fetch_products())
        warnings = source.warnings

    return CsvPreview(
        headers=headers,
        mapping=mapping,
        sample_rows=sample_rows,
        total_rows=total_rows,
        parsed_count=parsed_count,
        warnings=warnings[:WARNING_LIMIT],
        warning_count=len(warnings),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/sources/test_csv_preview.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/sources/csv_preview.py backend/tests/sources/test_csv_preview.py
git commit -m "Add build_csv_preview: live CSV parse preview without persisting anything"
```

---

## Task 3: `POST /csv/preview` endpoint + shared mapping-form-parsing helper

**Files:**
- Modify: `backend/app/scans/api.py`
- Modify: `backend/tests/scans/test_api.py`

**Interfaces:**
- Consumes: `ColumnMapping` from `app.sources.column_mapping`; `CsvPreview`, `build_csv_preview`
  from Task 2's `app.sources.csv_preview`.
- Produces: `_column_mapping_from_form(name_column, wholesale_price_column, ean_column,
  category_column, sku_column) -> ColumnMapping | None` (raises `HTTPException(400)` on a partial
  subset of the 4 required fields; returns `None` if none are given; returns a complete
  `ColumnMapping` if all 4 are given) — reused by Task 4's modified `POST /scans`. New route:
  `POST /csv/preview` (multipart: `file`, plus the same 5 optional form fields), returning the
  `CsvPreview` JSON shape documented in the design spec.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/scans/test_api.py` (it already defines `CSV_BYTES` and imports `router`,
`TestClient`, `io` at module scope — reuse them):

```python
def test_csv_preview_returns_auto_detected_mapping_and_sample_rows(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/csv/preview", files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["headers"] == ["nazwa", "cena", "ean", "kategoria"]
    assert body["mapping"] == {
        "name": "nazwa", "wholesale_price": "cena", "ean": "ean", "category": "kategoria", "sku": None,
    }
    assert body["total_rows"] == 1
    assert body["parsed_count"] == 1
    assert body["sample_rows"][0]["nazwa"] == "Produkt A"


def test_csv_preview_returns_null_for_unresolved_field_instead_of_400(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)
    csv_bytes = ("nazwa;kategoria\nProdukt A;Elektronika\n").encode("utf-8")

    response = client.post(
        "/csv/preview", files={"file": ("catalog.csv", io.BytesIO(csv_bytes), "text/csv")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mapping"]["wholesale_price"] is None
    assert body["mapping"]["ean"] is None
    assert body["parsed_count"] == 0


def test_csv_preview_honors_a_full_mapping_override(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)
    # A header where the auto-detector would pick "cena" for price; override to point
    # wholesale_price at the ean column instead, to prove the override actually changes parsing.
    csv_bytes = (
        "nazwa;cena;ean;kategoria\n"
        "Produkt A;10,00;5901234123457;Elektronika\n"
    ).encode("utf-8")

    response = client.post(
        "/csv/preview",
        files={"file": ("catalog.csv", io.BytesIO(csv_bytes), "text/csv")},
        data={
            "name_column": "nazwa", "wholesale_price_column": "ean",
            "ean_column": "cena", "category_column": "kategoria",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mapping"]["wholesale_price"] == "ean"
    assert body["mapping"]["ean"] == "cena"


def test_csv_preview_rejects_partial_mapping_subset(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/csv/preview",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"name_column": "nazwa"},
    )

    assert response.status_code == 400


def test_csv_preview_rejects_empty_csv_file(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/csv/preview", files={"file": ("catalog.csv", io.BytesIO(b""), "text/csv")},
    )

    assert response.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/scans/test_api.py -v -k csv_preview`
Expected: FAIL with 404s (route doesn't exist yet)

- [ ] **Step 3: Write minimal implementation**

Add these imports to the top of `backend/app/scans/api.py`, alongside the existing
`from app.sources.column_mapping import ColumnMappingError` and
`from app.sources.csv_source import EmptyCsvError` lines:

```python
from app.sources.column_mapping import ColumnMapping, ColumnMappingError
from app.sources.csv_preview import CsvPreview, build_csv_preview
from app.sources.csv_source import EmptyCsvError
```

(This replaces the two existing single-symbol import lines — same modules, more symbols.)

Add these two helpers near the other `_..._to_dict` helpers (e.g. right after `_scan_to_dict`):

```python
def _csv_preview_to_dict(preview: CsvPreview) -> dict:
    return {
        "headers": preview.headers,
        "mapping": {
            "name": preview.mapping.name,
            "wholesale_price": preview.mapping.wholesale_price,
            "ean": preview.mapping.ean,
            "category": preview.mapping.category,
            "sku": preview.mapping.sku,
        },
        "sample_rows": preview.sample_rows,
        "total_rows": preview.total_rows,
        "parsed_count": preview.parsed_count,
        "warnings": preview.warnings,
        "warning_count": preview.warning_count,
    }


def _column_mapping_from_form(
    name_column: str | None,
    wholesale_price_column: str | None,
    ean_column: str | None,
    category_column: str | None,
    sku_column: str | None,
) -> ColumnMapping | None:
    required = (name_column, wholesale_price_column, ean_column, category_column)
    provided = [f for f in required if f is not None]
    if not provided:
        return None
    if len(provided) != len(required):
        raise HTTPException(
            status_code=400,
            detail=(
                "provide all of name_column/wholesale_price_column/ean_column/"
                "category_column, or none"
            ),
        )
    return ColumnMapping(
        name=name_column, wholesale_price=wholesale_price_column,
        ean=ean_column, category=category_column, sku=sku_column,
    )
```

Add the new route. A sensible place is right before `@router.post("/scans")`:

```python
@router.post("/csv/preview")
async def post_csv_preview(
    file: UploadFile,
    name_column: str | None = Form(None),
    wholesale_price_column: str | None = Form(None),
    ean_column: str | None = Form(None),
    category_column: str | None = Form(None),
    sku_column: str | None = Form(None),
):
    mapping = _column_mapping_from_form(
        name_column, wholesale_price_column, ean_column, category_column, sku_column,
    )
    csv_bytes = await file.read()
    try:
        preview = build_csv_preview(csv_bytes, tenant_id="default", mapping_override=mapping)
    except EmptyCsvError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _csv_preview_to_dict(preview)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/scans/test_api.py -v -k csv_preview`
Expected: PASS (5 tests)

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && .venv/bin/python -m pytest`
Expected: all pass, no regressions to the rest of `test_api.py`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/scans/api.py backend/tests/scans/test_api.py
git commit -m "Add POST /csv/preview endpoint and shared column-mapping form parsing"
```

---

## Task 4: `POST /scans` accepts a confirmed column mapping

**Files:**
- Modify: `backend/app/scans/orchestration.py`
- Modify: `backend/app/scans/api.py`
- Modify: `backend/tests/scans/test_api.py`

**Interfaces:**
- Consumes: `ColumnMapping` from `app.sources.column_mapping`; `_column_mapping_from_form` from
  Task 3's `app.scans.api` (module-local, no import needed — same file).
- Produces: `create_scan(..., column_mapping: ColumnMapping | None = None)` — the existing function
  gains one new optional keyword parameter, threaded into `CsvCatalogSource`. `POST /scans` gains the
  same 5 form fields as `POST /csv/preview`, applying the same all-4-or-none validation.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/scans/test_api.py`:

```python
def test_post_scans_honors_a_full_mapping_override(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)
    # Same trick as the /csv/preview override test: point wholesale_price at the ean
    # column to prove the override actually reaches parsing, not just validation.
    csv_bytes = (
        "nazwa;cena;ean;kategoria\n"
        "Produkt A;10,00;99,00;Elektronika\n"
    ).encode("utf-8")

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(csv_bytes), "text/csv")},
        data={
            "scope_type": "full",
            "name_column": "nazwa", "wholesale_price_column": "ean",
            "ean_column": "cena", "category_column": "kategoria",
        },
    )

    assert response.status_code == 200
    scan_id = response.json()["scan_id"]
    pending = store.list_pending(scan_id)
    assert len(pending) == 1
    # wholesale_price_column was overridden to the "ean" column (value "99,00"),
    # not the auto-detected "cena" column (value "10,00") -- proves the override won.
    assert pending[0].product.wholesale_price == Decimal("99.00")


def test_post_scans_rejects_partial_mapping_subset(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "full", "name_column": "nazwa"},
    )

    assert response.status_code == 400


def test_post_scans_still_works_with_no_mapping_fields(tmp_path):
    # Backward compatibility: existing callers that never supply a mapping
    # keep getting auto-detection, unchanged from before this task.
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "full"},
    )

    assert response.status_code == 200
```

`Decimal` and `io` are already imported at the top of `test_api.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/scans/test_api.py -v -k mapping`
Expected: FAIL — `test_post_scans_honors_a_full_mapping_override` fails because the override fields
are silently ignored by today's `post_scans` (the parsed wholesale price stays `Decimal("10.00")`,
not `Decimal("99.00")`); `test_post_scans_rejects_partial_mapping_subset` fails because today's
`post_scans` has no such fields to reject, so it returns 200.

- [ ] **Step 3: Write minimal implementation**

In `backend/app/scans/orchestration.py`, add the import and the new parameter:

```python
from app.sources.column_mapping import ColumnMapping
from app.sources.csv_source import CsvCatalogSource


def create_scan(
    *,
    csv_bytes: bytes,
    tenant_id: str,
    scope_type: str,
    sample_per_category: int | None,
    sample_seed: int,
    market: str,
    max_delivery_days: int,
    max_concurrency: int,
    staleness_threshold_days: int,
    store: ScanStore,
    cache: PriceCache,
    provider_name: str,
    column_mapping: ColumnMapping | None = None,
) -> tuple[str, list[str]]:
    source = CsvCatalogSource(csv_bytes, tenant_id=tenant_id, column_mapping=column_mapping)
    all_products = source.fetch_products()
    # ... rest of the function is unchanged
```

(Only the function signature and the `CsvCatalogSource(...)` call line change — everything after
`all_products = source.fetch_products()` stays exactly as it is today.)

In `backend/app/scans/api.py`, modify `post_scans`'s signature and body:

```python
@router.post("/scans")
async def post_scans(
    file: UploadFile,
    scope_type: str = Form(...),
    sample_per_category: int | None = Form(None),
    market: str = Form("PL"),
    max_delivery_days: int = Form(5),
    max_concurrency: int = Form(5),
    staleness_threshold_days: int = Form(14),
    name_column: str | None = Form(None),
    wholesale_price_column: str | None = Form(None),
    ean_column: str | None = Form(None),
    category_column: str | None = Form(None),
    sku_column: str | None = Form(None),
    store: ScanStore = Depends(get_store),
    cache: PriceCache = Depends(get_cache),
    provider: PriceProvider = Depends(get_provider),
):
    if scope_type not in VALID_SCOPE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"scope_type must be one of {VALID_SCOPE_TYPES!r}, got {scope_type!r}",
        )
    if max_concurrency < 1:
        raise HTTPException(
            status_code=400, detail=f"max_concurrency must be >= 1, got {max_concurrency!r}"
        )
    if max_delivery_days < 1:
        raise HTTPException(
            status_code=400, detail=f"max_delivery_days must be >= 1, got {max_delivery_days!r}"
        )
    if staleness_threshold_days < 0:
        raise HTTPException(
            status_code=400,
            detail=f"staleness_threshold_days must be >= 0, got {staleness_threshold_days!r}",
        )
    if scope_type == "sample" and (sample_per_category is None or sample_per_category < 1):
        raise HTTPException(
            status_code=400,
            detail="sample_per_category must be >= 1 when scope_type is 'sample'",
        )

    column_mapping = _column_mapping_from_form(
        name_column, wholesale_price_column, ean_column, category_column, sku_column,
    )

    csv_bytes = await file.read()
    try:
        scan_id, warnings = create_scan(
            csv_bytes=csv_bytes, tenant_id="default", scope_type=scope_type,
            sample_per_category=sample_per_category, sample_seed=_sample_seed_from_csv(csv_bytes),
            market=market, max_delivery_days=max_delivery_days, max_concurrency=max_concurrency,
            staleness_threshold_days=staleness_threshold_days, column_mapping=column_mapping,
            store=store, cache=cache, provider_name=provider.name,
        )
    except (EmptyCsvError, ColumnMappingError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    scan = store.get_scan(scan_id)
    result = _scan_to_dict(scan)
    result["warnings"] = warnings
    return result
```

(All the validation `if` blocks are unchanged and stay in the same order — only the new
`column_mapping = _column_mapping_from_form(...)` line is added, right after the existing
validation blocks and before `csv_bytes = await file.read()`, plus `column_mapping=column_mapping`
added to the `create_scan(...)` call.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/scans/test_api.py -v`
Expected: PASS (all tests in the file, including the 3 new ones)

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && .venv/bin/python -m pytest`
Expected: all pass — this is the last backend task, so this is the final backend regression check
for the whole phase.

- [ ] **Step 6: Commit**

```bash
git add backend/app/scans/orchestration.py backend/app/scans/api.py backend/tests/scans/test_api.py
git commit -m "Thread a confirmed column mapping from POST /scans into CsvCatalogSource"
```

---

## Task 5: Frontend API types, client functions, and dev proxy

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/client.test.ts`
- Modify: `frontend/vite.config.ts`

**Interfaces:**
- Produces: `ColumnMapping` (`{ name: string | null; wholesale_price: string | null; ean: string |
  null; category: string | null; sku: string | null }`, mirroring the backend's field names
  directly — used both as the shape `CsvPreview.mapping` comes back as, and as the shape sent to
  `getCsvPreview`/`createScan`, so no camelCase/snake_case translation layer is needed for this
  type), `CsvPreview` (mirrors Task 3's JSON exactly: `headers: string[]`, `mapping: ColumnMapping`,
  `sample_rows: Record<string, string>[]`, `total_rows: number`, `parsed_count: number`, `warnings:
  string[]`, `warning_count: number`). Functions: `getCsvPreview(file: File, mappingOverride?:
  ColumnMapping): Promise<CsvPreview>`; `createScan`'s existing signature grows a third, optional
  `columnMapping?: ColumnMapping` parameter. Both throw `ApiError` on a non-2xx response, matching
  every other `client.ts` function. Used by Task 6's `MappingStep` and Task 7's `ScopeEstimateStep`.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/api/client.test.ts`. First, update its existing top-of-file imports (it
currently has `import { createScan, getScan, startScan, getReportSummary, getReportProducts } from
'./client'` and `import type { ScopeConfig } from './types'`) to also pull in the new symbols:

```ts
import { createScan, getScan, startScan, getReportSummary, getReportProducts, getCsvPreview } from './client'
import type { ColumnMapping, ScopeConfig } from './types'
```

Then append:

```ts
const CSV_PREVIEW = {
  headers: ['Nazwa', 'Cena hurtowa', 'EAN', 'Kategoria'],
  mapping: { name: 'Nazwa', wholesale_price: 'Cena hurtowa', ean: 'EAN', category: 'Kategoria', sku: null },
  sample_rows: [{ Nazwa: 'Produkt A', 'Cena hurtowa': '10,00', EAN: '5901234123457', Kategoria: 'Elektronika' }],
  total_rows: 1,
  parsed_count: 1,
  warnings: [],
  warning_count: 0,
}

describe('getCsvPreview', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('posts the file with no mapping fields when no override is given', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(CSV_PREVIEW))
    const file = new File(['a,b\n1,2'], 'catalog.csv', { type: 'text/csv' })

    const result = await getCsvPreview(file)

    expect(result).toEqual(CSV_PREVIEW)
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/csv/preview')
    expect(init?.method).toBe('POST')
    const body = init?.body as FormData
    expect(body.get('file')).toBeInstanceOf(File)
    expect(body.get('name_column')).toBeNull()
  })

  it('posts only the non-null mapping fields when an override is given', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(CSV_PREVIEW))
    const file = new File(['a,b\n1,2'], 'catalog.csv', { type: 'text/csv' })
    const mapping: ColumnMapping = {
      name: 'Nazwa', wholesale_price: 'Cena hurtowa', ean: 'EAN', category: 'Kategoria', sku: null,
    }

    await getCsvPreview(file, mapping)

    const [, init] = vi.mocked(fetch).mock.calls[0]
    const body = init?.body as FormData
    expect(body.get('name_column')).toBe('Nazwa')
    expect(body.get('wholesale_price_column')).toBe('Cena hurtowa')
    expect(body.get('ean_column')).toBe('EAN')
    expect(body.get('category_column')).toBe('Kategoria')
    expect(body.get('sku_column')).toBeNull()
  })

  it('throws ApiError on a non-2xx response', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: 'CSV file has no header row' }, 400))
    const file = new File([''], 'catalog.csv', { type: 'text/csv' })

    await expect(getCsvPreview(file)).rejects.toMatchObject({ status: 400 })
  })
})

describe('createScan with a column mapping', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('includes mapping fields in the form data when columnMapping is provided', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({
        scan_id: 'scan-1', status: 'estimated', scope_type: 'full',
        total_products: 1, completed_products: 0,
        estimate: {
          queries_without_refresh: 1, queries_with_refresh: 1,
          cost_usd_without_refresh: '0.01', cost_usd_with_refresh: '0.01',
          seconds_without_refresh: 1, seconds_with_refresh: 1,
        },
        overlapping_count: 0, stale_count: 0, warnings: [],
      }),
    )
    const file = new File(['a,b\n1,2'], 'catalog.csv', { type: 'text/csv' })
    const mapping: ColumnMapping = {
      name: 'Nazwa', wholesale_price: 'Cena hurtowa', ean: 'EAN', category: 'Kategoria', sku: 'SKU',
    }
    const scope: ScopeConfig = {
      scopeType: 'full', market: 'PL', maxDeliveryDays: 5, maxConcurrency: 5, stalenessThresholdDays: 14,
    }

    await createScan(file, scope, mapping)

    const [, init] = vi.mocked(fetch).mock.calls[0]
    const body = init?.body as FormData
    expect(body.get('name_column')).toBe('Nazwa')
    expect(body.get('sku_column')).toBe('SKU')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL with `Cannot find module` / TS errors — `getCsvPreview` and `ColumnMapping` don't
exist yet.

- [ ] **Step 3: Write minimal implementation**

Append to `frontend/src/api/types.ts`:

```ts
export interface ColumnMapping {
  name: string | null
  wholesale_price: string | null
  ean: string | null
  category: string | null
  sku: string | null
}

export interface CsvPreview {
  headers: string[]
  mapping: ColumnMapping
  sample_rows: Record<string, string>[]
  total_rows: number
  parsed_count: number
  warnings: string[]
  warning_count: number
}
```

In `frontend/src/api/client.ts`, add a new `import type` line alongside the existing ones at the
top:

```ts
import type { ColumnMapping, CsvPreview } from './types'
```

Add this helper right after `errorDetail` (before `createScan`):

```ts
function appendColumnMapping(formData: FormData, mapping: ColumnMapping): void {
  if (mapping.name !== null) formData.append('name_column', mapping.name)
  if (mapping.wholesale_price !== null) formData.append('wholesale_price_column', mapping.wholesale_price)
  if (mapping.ean !== null) formData.append('ean_column', mapping.ean)
  if (mapping.category !== null) formData.append('category_column', mapping.category)
  if (mapping.sku !== null) formData.append('sku_column', mapping.sku)
}
```

Modify the existing `createScan` function to accept and use the new optional parameter (only the
signature line and the one new call to `appendColumnMapping` are added — everything else in the
function body is unchanged):

```ts
export async function createScan(
  file: File,
  scope: ScopeConfig,
  columnMapping?: ColumnMapping,
): Promise<CreateScanResult> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('scope_type', scope.scopeType)
  if (scope.samplePerCategory !== undefined) {
    formData.append('sample_per_category', String(scope.samplePerCategory))
  }
  formData.append('market', scope.market)
  formData.append('max_delivery_days', String(scope.maxDeliveryDays))
  formData.append('max_concurrency', String(scope.maxConcurrency))
  formData.append('staleness_threshold_days', String(scope.stalenessThresholdDays))
  if (columnMapping) appendColumnMapping(formData, columnMapping)

  const response = await fetch('/scans', { method: 'POST', body: formData })
  if (!response.ok) {
    throw new ApiError(await errorDetail(response), response.status)
  }
  return response.json()
}
```

Add the new function at the end of the file:

```ts
export async function getCsvPreview(file: File, mappingOverride?: ColumnMapping): Promise<CsvPreview> {
  const formData = new FormData()
  formData.append('file', file)
  if (mappingOverride) appendColumnMapping(formData, mappingOverride)

  const response = await fetch('/csv/preview', { method: 'POST', body: formData })
  if (!response.ok) {
    throw new ApiError(await errorDetail(response), response.status)
  }
  return response.json()
}
```

In `frontend/vite.config.ts`, add `/csv` to the existing proxy map (this is what makes
`POST /csv/preview` reachable through the dev server in an actual browser — the Vitest tests above
mock `fetch` directly and don't depend on this, but real dev usage does):

```ts
    proxy: {
      '/scans': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
      '/csv': 'http://localhost:8000',
    },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (all `client.test.ts` tests, including the 4 new ones)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/api/client.test.ts frontend/vite.config.ts
git commit -m "Add ColumnMapping/CsvPreview types, getCsvPreview client, and /csv dev proxy"
```

---

## Task 6: `MappingStep` component

**Files:**
- Create: `frontend/src/steps/MappingStep.tsx`
- Create: `frontend/src/steps/MappingStep.test.tsx`

**Interfaces:**
- Consumes: `getCsvPreview` from Task 5's `../api/client`; `ColumnMapping`, `CsvPreview` from
  `../api/types`.
- Produces: `MappingStep({ file, onConfirmed }: { file: File; onConfirmed: (mapping: ColumnMapping)
  => void })`. On mount, loads a preview with no override (pure auto-detection). Renders a
  grouped-card of 5 dropdowns (4 required + SKU), an "Odśwież podgląd" button, parsed-count/warnings
  display, and a sample-rows table. "Dalej" is disabled until all 4 required dropdowns have a
  non-blank selection; clicking it calls `onConfirmed` with the current mapping. Used by Task 7's
  `App.tsx`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/steps/MappingStep.test.tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MappingStep } from './MappingStep'
import * as client from '../api/client'
import type { CsvPreview } from '../api/types'

const FILE = new File(['nazwa;cena'], 'catalog.csv', { type: 'text/csv' })

const PREVIEW: CsvPreview = {
  headers: ['Nazwa', 'Cena hurtowa', 'EAN', 'Kategoria', 'SKU'],
  mapping: { name: 'Nazwa', wholesale_price: 'Cena hurtowa', ean: 'EAN', category: 'Kategoria', sku: 'SKU' },
  sample_rows: [
    { Nazwa: 'Produkt A', 'Cena hurtowa': '10,00', EAN: '5901234123457', Kategoria: 'Elektronika', SKU: 'A1' },
  ],
  total_rows: 1,
  parsed_count: 1,
  warnings: [],
  warning_count: 0,
}

beforeEach(() => {
  vi.restoreAllMocks()
})
afterEach(() => {
  vi.restoreAllMocks()
})

describe('MappingStep', () => {
  it('loads the preview on mount and pre-selects the auto-detected columns', async () => {
    vi.spyOn(client, 'getCsvPreview').mockResolvedValue(PREVIEW)
    render(<MappingStep file={FILE} onConfirmed={vi.fn()} />)

    await screen.findByText('1 / 1 wierszy sparsowanych poprawnie')
    expect(screen.getByLabelText('Nazwa')).toHaveValue('Nazwa')
    expect(screen.getByLabelText('Cena hurtowa')).toHaveValue('Cena hurtowa')
    expect(screen.getByLabelText('EAN')).toHaveValue('EAN')
    expect(screen.getByLabelText('Kategoria')).toHaveValue('Kategoria')
    expect(screen.getByLabelText('SKU (opcjonalne)')).toHaveValue('SKU')
  })

  it('shows the sample rows table', async () => {
    vi.spyOn(client, 'getCsvPreview').mockResolvedValue(PREVIEW)
    render(<MappingStep file={FILE} onConfirmed={vi.fn()} />)

    await screen.findByText('Produkt A')
    expect(screen.getByText('5901234123457')).toBeInTheDocument()
  })

  it('shows truncated warnings with a remaining count', async () => {
    vi.spyOn(client, 'getCsvPreview').mockResolvedValue({
      ...PREVIEW,
      parsed_count: 3,
      total_rows: 25,
      warnings: ['Row 2: missing name, skipped'],
      warning_count: 22,
    })
    render(<MappingStep file={FILE} onConfirmed={vi.fn()} />)

    await screen.findByText('Row 2: missing name, skipped')
    expect(screen.getByText('...i 21 więcej')).toBeInTheDocument()
  })

  it('re-fetches the preview with the edited mapping when Odśwież podgląd is clicked', async () => {
    const spy = vi.spyOn(client, 'getCsvPreview').mockResolvedValue(PREVIEW)
    render(<MappingStep file={FILE} onConfirmed={vi.fn()} />)
    await screen.findByText('1 / 1 wierszy sparsowanych poprawnie')

    await userEvent.selectOptions(screen.getByLabelText('EAN'), 'Kategoria')
    await userEvent.click(screen.getByRole('button', { name: 'Odśwież podgląd' }))

    await waitFor(() =>
      expect(spy).toHaveBeenLastCalledWith(FILE, {
        name: 'Nazwa', wholesale_price: 'Cena hurtowa', ean: 'Kategoria', category: 'Kategoria', sku: 'SKU',
      }),
    )
  })

  it('disables Dalej until all required fields are mapped, and confirms the current mapping when clicked', async () => {
    vi.spyOn(client, 'getCsvPreview').mockResolvedValue({
      ...PREVIEW,
      mapping: { name: 'Nazwa', wholesale_price: null, ean: 'EAN', category: 'Kategoria', sku: null },
    })
    const onConfirmed = vi.fn()
    render(<MappingStep file={FILE} onConfirmed={onConfirmed} />)
    await screen.findByText('Produkt A')

    expect(screen.getByRole('button', { name: 'Dalej' })).toBeDisabled()

    await userEvent.selectOptions(screen.getByLabelText('Cena hurtowa'), 'Cena hurtowa')
    expect(screen.getByRole('button', { name: 'Dalej' })).toBeEnabled()

    await userEvent.click(screen.getByRole('button', { name: 'Dalej' }))

    expect(onConfirmed).toHaveBeenCalledWith({
      name: 'Nazwa', wholesale_price: 'Cena hurtowa', ean: 'EAN', category: 'Kategoria', sku: null,
    })
  })

  it('shows the API error message when the preview request fails', async () => {
    const { ApiError } = await import('../api/types')
    vi.spyOn(client, 'getCsvPreview').mockRejectedValue(new ApiError('CSV file has no header row', 400))
    render(<MappingStep file={FILE} onConfirmed={vi.fn()} />)

    expect(await screen.findByText('CSV file has no header row')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL with `Cannot find module './MappingStep'`

- [ ] **Step 3: Write minimal implementation**

```tsx
// frontend/src/steps/MappingStep.tsx
import { useEffect, useState } from 'react'
import { getCsvPreview } from '../api/client'
import { ApiError } from '../api/types'
import type { ColumnMapping, CsvPreview } from '../api/types'

const EMPTY_MAPPING: ColumnMapping = {
  name: null,
  wholesale_price: null,
  ean: null,
  category: null,
  sku: null,
}

interface MappingStepProps {
  file: File
  onConfirmed: (mapping: ColumnMapping) => void
}

export function MappingStep({ file, onConfirmed }: MappingStepProps) {
  const [preview, setPreview] = useState<CsvPreview | null>(null)
  const [mapping, setMapping] = useState<ColumnMapping>(EMPTY_MAPPING)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  async function loadPreview(override?: ColumnMapping) {
    setError(null)
    setIsLoading(true)
    try {
      const result = await getCsvPreview(file, override)
      setPreview(result)
      setMapping(result.mapping)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Nie udało się wczytać podglądu pliku')
    } finally {
      setIsLoading(false)
    }
  }

  // Runs once, on mount, for pure auto-detection. Every later refresh is the
  // explicit "Odśwież podgląd" button below -- never triggered by editing a
  // dropdown, matching the explicit-recompute pattern used throughout this wizard.
  useEffect(() => {
    loadPreview()
  }, [file])

  function handleFieldChange(field: keyof ColumnMapping, value: string) {
    setMapping({ ...mapping, [field]: value || null })
  }

  function handleRefresh() {
    loadPreview(mapping)
  }

  const requiredFilled = Boolean(
    mapping.name && mapping.wholesale_price && mapping.ean && mapping.category,
  )

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-12 p-8">
      <h1 className="text-xl font-semibold text-slate-100">Mapowanie kolumn</h1>

      {error && <p className="text-sm text-red-400">{error}</p>}

      {preview && (
        <>
          <section className="flex flex-col gap-4">
            <div className="divide-y divide-slate-800/60 rounded-2xl border border-slate-800 bg-slate-900/40">
              <label className="flex items-center justify-between gap-4 p-4 text-sm text-slate-300">
                Nazwa
                <select
                  value={mapping.name ?? ''}
                  onChange={(e) => handleFieldChange('name', e.target.value)}
                  className="w-56 rounded-lg border border-slate-700 bg-slate-950 p-2 text-slate-100"
                >
                  <option value="">— wybierz —</option>
                  {preview.headers.map((h) => (
                    <option key={h} value={h}>{h}</option>
                  ))}
                </select>
              </label>
              <label className="flex items-center justify-between gap-4 p-4 text-sm text-slate-300">
                Cena hurtowa
                <select
                  value={mapping.wholesale_price ?? ''}
                  onChange={(e) => handleFieldChange('wholesale_price', e.target.value)}
                  className="w-56 rounded-lg border border-slate-700 bg-slate-950 p-2 text-slate-100"
                >
                  <option value="">— wybierz —</option>
                  {preview.headers.map((h) => (
                    <option key={h} value={h}>{h}</option>
                  ))}
                </select>
              </label>
              <label className="flex items-center justify-between gap-4 p-4 text-sm text-slate-300">
                EAN
                <select
                  value={mapping.ean ?? ''}
                  onChange={(e) => handleFieldChange('ean', e.target.value)}
                  className="w-56 rounded-lg border border-slate-700 bg-slate-950 p-2 text-slate-100"
                >
                  <option value="">— wybierz —</option>
                  {preview.headers.map((h) => (
                    <option key={h} value={h}>{h}</option>
                  ))}
                </select>
              </label>
              <label className="flex items-center justify-between gap-4 p-4 text-sm text-slate-300">
                Kategoria
                <select
                  value={mapping.category ?? ''}
                  onChange={(e) => handleFieldChange('category', e.target.value)}
                  className="w-56 rounded-lg border border-slate-700 bg-slate-950 p-2 text-slate-100"
                >
                  <option value="">— wybierz —</option>
                  {preview.headers.map((h) => (
                    <option key={h} value={h}>{h}</option>
                  ))}
                </select>
              </label>
              <label className="flex items-center justify-between gap-4 p-4 text-sm text-slate-300">
                SKU (opcjonalne)
                <select
                  value={mapping.sku ?? ''}
                  onChange={(e) => handleFieldChange('sku', e.target.value)}
                  className="w-56 rounded-lg border border-slate-700 bg-slate-950 p-2 text-slate-100"
                >
                  <option value="">— brak —</option>
                  {preview.headers.map((h) => (
                    <option key={h} value={h}>{h}</option>
                  ))}
                </select>
              </label>
            </div>
            <button
              type="button"
              onClick={handleRefresh}
              disabled={isLoading}
              className="self-start rounded-md bg-emerald-600 px-4 py-2 font-medium text-slate-950 disabled:bg-slate-700 disabled:text-slate-400"
            >
              Odśwież podgląd
            </button>
          </section>

          <section className="flex flex-col gap-2 text-sm text-slate-300">
            <p>
              {preview.parsed_count} / {preview.total_rows} wierszy sparsowanych poprawnie
            </p>
            {preview.warnings.length > 0 && (
              <ul className="list-inside list-disc text-amber-400">
                {preview.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
                {preview.warning_count > preview.warnings.length && (
                  <li>...i {preview.warning_count - preview.warnings.length} więcej</li>
                )}
              </ul>
            )}
          </section>

          {preview.sample_rows.length > 0 && (
            <section className="flex flex-col gap-2">
              <h2 className="text-sm font-medium text-slate-400">Przykładowe wiersze</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-800/60 text-left text-slate-500">
                      {preview.headers.map((h) => (
                        <th key={h} className="py-2 pr-4 font-normal">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.sample_rows.map((row, i) => (
                      <tr key={i} className="border-b border-slate-800/60">
                        {preview.headers.map((h) => (
                          <td key={h} className="py-2 pr-4 text-slate-300">{row[h] ?? ''}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          <button
            type="button"
            onClick={() => onConfirmed(mapping)}
            disabled={!requiredFilled}
            className="self-start rounded-md bg-emerald-600 px-4 py-2 font-medium text-slate-950 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
          >
            Dalej
          </button>
        </>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (6 tests)

- [ ] **Step 5: Run the linter**

Run: `cd frontend && npm run lint`
Expected: clean (or only the pre-existing warnings already present in `ReportStep.tsx` from Phase
5b — nothing new from this file).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/steps/MappingStep.tsx frontend/src/steps/MappingStep.test.tsx
git commit -m "Add MappingStep: column-mapping dropdowns, live preview, sample-rows table"
```

---

## Task 7: Wire `MappingStep` into the wizard

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.test.tsx`
- Modify: `frontend/src/steps/ScopeEstimateStep.tsx`
- Modify: `frontend/src/steps/ScopeEstimateStep.test.tsx`

**Interfaces:**
- Consumes: `MappingStep` from Task 6's `./steps/MappingStep`.
- Produces: `App`'s `WizardStep` gains `'mapping'`, inserted between `'upload'` and `'scope'`.
  `ScopeEstimateStep` gains a required `columnMapping: ColumnMapping` prop, passed straight through
  to its `createScan` call.

- [ ] **Step 1: Write the failing test**

First, update every one of the 7 `render(<ScopeEstimateStep file={FILE} onStarted={...} />)` calls
in `frontend/src/steps/ScopeEstimateStep.test.tsx` to include a `columnMapping` prop:

```tsx
const MAPPING: ColumnMapping = {
  name: 'nazwa', wholesale_price: 'cena', ean: 'ean', category: 'kategoria', sku: null,
}
```

(Add this constant near the top of the file, alongside the existing `FILE`/`CREATE_RESULT`
constants, and add `import type { ColumnMapping } from '../api/types'` to the file's imports.) Then
change each of the 7 render calls from:

```tsx
render(<ScopeEstimateStep file={FILE} onStarted={vi.fn()} />)
```

to:

```tsx
render(<ScopeEstimateStep file={FILE} onStarted={vi.fn()} columnMapping={MAPPING} />)
```

(and the one with a named `onStarted` variable similarly gains `columnMapping={MAPPING}`). Also add
one new test, asserting the mapping is actually forwarded to `createScan`:

```tsx
  it('passes the confirmed column mapping through to createScan', async () => {
    const createScanSpy = vi.spyOn(client, 'createScan').mockResolvedValue(CREATE_RESULT)
    render(<ScopeEstimateStep file={FILE} onStarted={vi.fn()} columnMapping={MAPPING} />)

    await userEvent.click(screen.getByRole('button', { name: 'Oszacuj koszt' }))

    await waitFor(() => expect(createScanSpy).toHaveBeenCalledTimes(1))
    expect(createScanSpy).toHaveBeenCalledWith(FILE, expect.anything(), MAPPING)
  })
```

Then update `frontend/src/App.test.tsx`'s two existing tests: each currently does
`await userEvent.click(screen.getByRole('button', { name: 'Dalej' }))` right after uploading the
file, and immediately asserts `await screen.findByRole('heading', { name: 'Zakres skanu' })`. Insert
the mapping step in between. Both tests need `vi.spyOn(client, 'getCsvPreview').mockResolvedValue(...)`
added to their mock setup, and the following inserted between the upload-`Dalej`-click and the
`Zakres skanu` assertion:

```tsx
    await screen.findByRole('heading', { name: 'Mapowanie kolumn' })
    await userEvent.click(screen.getByRole('button', { name: 'Dalej' }))
```

For the mock, add this to both tests' `vi.spyOn` blocks (any complete mapping works since the test
only needs "Dalej" to be enabled):

```tsx
    vi.spyOn(client, 'getCsvPreview').mockResolvedValue({
      headers: ['nazwa', 'cena', 'ean', 'kategoria'],
      mapping: { name: 'nazwa', wholesale_price: 'cena', ean: 'ean', category: 'kategoria', sku: null },
      sample_rows: [],
      total_rows: 0,
      parsed_count: 0,
      warnings: [],
      warning_count: 0,
    })
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `ScopeEstimateStep`'s TypeScript compilation fails (`columnMapping` prop doesn't
exist yet), and `App.test.tsx`'s two tests fail because there's no "Mapowanie kolumn" heading to
find (the wizard still jumps straight from Upload to Scope+Estimate).

- [ ] **Step 3: Write minimal implementation**

Replace `frontend/src/App.tsx` in full:

```tsx
// frontend/src/App.tsx
import { useState } from 'react'
import { UploadStep } from './steps/UploadStep'
import { MappingStep } from './steps/MappingStep'
import { ScopeEstimateStep } from './steps/ScopeEstimateStep'
import { ProgressStep } from './steps/ProgressStep'
import { ReportStep } from './steps/ReportStep'
import type { ColumnMapping } from './api/types'

type WizardStep = 'upload' | 'mapping' | 'scope' | 'progress' | 'report'

function App() {
  const [step, setStep] = useState<WizardStep>('upload')
  const [file, setFile] = useState<File | null>(null)
  const [columnMapping, setColumnMapping] = useState<ColumnMapping | null>(null)
  const [scanId, setScanId] = useState<string | null>(null)

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      {step === 'upload' && (
        <UploadStep
          onFileSelected={(selected) => {
            setFile(selected)
            setStep('mapping')
          }}
        />
      )}
      {step === 'mapping' && file && (
        <MappingStep
          file={file}
          onConfirmed={(mapping) => {
            setColumnMapping(mapping)
            setStep('scope')
          }}
        />
      )}
      {step === 'scope' && file && columnMapping && (
        <ScopeEstimateStep
          file={file}
          columnMapping={columnMapping}
          onStarted={(id) => {
            setScanId(id)
            setStep('progress')
          }}
        />
      )}
      {step === 'progress' && scanId && (
        <ProgressStep scanId={scanId} onDone={() => setStep('report')} />
      )}
      {step === 'report' && scanId && <ReportStep scanId={scanId} />}
    </div>
  )
}

export default App
```

In `frontend/src/steps/ScopeEstimateStep.tsx`, add the new prop and thread it into `createScan`.
Change the props interface and the component signature:

```tsx
import type { ColumnMapping, CreateScanResult, ScopeType } from '../api/types'

interface ScopeEstimateStepProps {
  file: File
  columnMapping: ColumnMapping
  onStarted: (scanId: string) => void
}

export function ScopeEstimateStep({ file, columnMapping, onStarted }: ScopeEstimateStepProps) {
```

And change the `createScan` call inside `handleEstimate` to pass it as the third argument:

```tsx
      const created = await createScan(
        file,
        {
          scopeType,
          samplePerCategory: scopeType === 'sample' ? Number(samplePerCategory) : undefined,
          market: 'PL',
          maxDeliveryDays,
          maxConcurrency,
          stalenessThresholdDays,
        },
        columnMapping,
      )
```

(Every other line in `ScopeEstimateStep.tsx` — state, handlers, JSX — is unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS — full suite green (Tasks 1-7 combined, all prior phases' tests included).

- [ ] **Step 5: Run the linter**

Run: `cd frontend && npm run lint`
Expected: clean (aside from the pre-existing `ReportStep.tsx` warnings from Phase 5b).

- [ ] **Step 6: Run `npm run build`**

Run: `cd frontend && npm run build`
Expected: exits 0. (Phase 5b's final review found a real TypeScript build failure that `vitest`
alone never caught — always confirm `tsc -b` passes before calling a frontend phase done.)

- [ ] **Step 7: Run the full backend suite once more for a final full-stack check**

Run: `cd backend && .venv/bin/python -m pytest`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx frontend/src/steps/ScopeEstimateStep.tsx frontend/src/steps/ScopeEstimateStep.test.tsx
git commit -m "Wire MappingStep into the wizard between Upload and Scope+Estimate"
```

---

## Self-Review Notes

- **Spec coverage:** auto-detection failure never blocking preview — Task 1's
  `detect_column_mapping_partial` + Task 2's graceful skip of parsing when a required field is still
  `None`. Live validation via a full re-parse, capped sample rows (10) and warnings (20 +
  `warning_count`) — Task 2. File re-uploaded a second time to `POST /scans` rather than staged
  server-side — Task 5's `createScan` change + Task 7's `App.tsx` keeping the same `File` in state.
  All-4-or-none mapping validation shared between both endpoints — Task 3's
  `_column_mapping_from_form`, reused unmodified by Task 4. No new visual design pass — Task 6
  reuses `ReportStep`'s exact card/hairline-table/explicit-button system. `npm run build` gate
  explicitly added to Task 7's verification steps, learned from Phase 5b's final review.
- **Placeholder scan:** none — every step has complete, runnable code.
- **Type consistency:** `ColumnMapping`'s five field names (`name`/`wholesale_price`/`ean`/
  `category`/`sku`) are used identically across the backend (`column_mapping.py`, `csv_preview.py`,
  `api.py`'s dict builder) and the frontend (`types.ts`, `client.ts`'s `appendColumnMapping`,
  `MappingStep.tsx`'s state, `ScopeEstimateStep.tsx`'s prop) — no renaming anywhere in the chain.
  `CsvPreview`'s seven fields match field-for-field between Task 2's dataclass, Task 3's
  `_csv_preview_to_dict`, and Task 5's TypeScript interface. `onConfirmed`/`columnMapping` prop names
  match between `MappingStep`'s definition (Task 6) and `App.tsx`'s usage (Task 7).

## Next steps after this plan

This closes the last deliberately-deferred piece of the original main design spec's wizard flow
(`Upload → Mapping → Scope+Estimate → Progress → Report` is now complete end-to-end). The standing,
dated commitment from Handoff 2 remains open: after a real scan runs against the user's actual
~115k-row catalog, check the percentage of Perplexity results coming back `found=false` or
low-confidence, and revisit open-web SERP as a supplementary source only if that number is high.
