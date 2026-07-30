# Phase 5c — Column-mapping correction screen — design spec

Status: **approved** (2026-07-30, via interactive brainstorming).

## Context

Since Phase 4, `POST /scans` auto-detects CSV column mapping (name / wholesale price / EAN /
category, plus optional SKU) via `detect_column_mapping` and commits immediately — there is no
preview or correction step. This was an explicit, deliberate deferral (see Phase 4's design spec).
The original main design spec's intended flow is `Upload → column-mapping correction →
Scope+Estimate → Progress → Report`; Phase 5a shipped everything except the mapping-correction
screen, and Phase 5b added Report. This phase closes that gap: `Upload → Mapping → Scope+Estimate →
Progress → Report`.

## Key finding that shapes this design

`CsvCatalogSource` (`backend/app/sources/csv_source.py`) already accepts an optional
`column_mapping: ColumnMapping | None` constructor argument and falls back to
`detect_column_mapping` only when none is given. This means overriding the mapping used for parsing
requires no changes to parsing logic at all — only a way to *produce* a candidate mapping for the
user to inspect/correct before it's confirmed, and a way to carry that confirmed mapping into the
existing `POST /scans` call. The whole design follows from reusing `CsvCatalogSource.fetch_products()`
verbatim for both preview and the real scan, so there is exactly one place that parses a CSV row into
a `Product`.

## Decisions

| Topic | Decision |
|---|---|
| Auto-detection failure | Never a hard error at preview time. A field detect can't resolve becomes `null` in the response; the frontend renders it as an empty dropdown the user must fill manually. `detect_column_mapping` (existing, raising) is untouched and still used by direct/backward-compatible `POST /scans` callers that skip the mapping screen entirely. |
| Live validation feedback | The preview endpoint always runs a full parse (via `CsvCatalogSource.fetch_products()`) against whatever mapping is currently resolved (auto-detected or user-supplied), returning real counts and warnings — not just raw column peeking. Refreshed only on an explicit "Odśwież podgląd" action, matching the explicit-recompute pattern already established by Report's "Przelicz" and Scope+Estimate's "Oszacuj koszt" — never on every dropdown change. |
| Getting the confirmed mapping to `POST /scans` | The frontend re-sends the same `File` object a second time (already held in wizard state) to `POST /scans`, now with the confirmed mapping as extra form fields. No server-side file staging/session — matches the existing pattern where the file is only ever sent as part of a specific request. |
| Sample rows shown | Raw CSV rows (all original columns, not just the 4 mapped fields) so the user can see actual column contents to decide what maps where — not only the columns the system already thinks it recognizes. |
| Payload size at scale | Sample rows capped at 10. Warnings capped at 20 with a `warning_count` total, so a ~115k-row catalog with many bad rows doesn't inflate the preview response — mirrors the counts-visible-but-bounded pattern from Report's exclusion chips. |
| Visual direction | No new design pass — continues the system established in Phase 5b's `ReportStep` exactly: `slate-950`/`emerald-600` palette, `rounded-2xl` grouped-card for the mapping fields (Settings.app-style rows), hairline table for the sample-rows preview, explicit-action buttons instead of live recompute. |

## Backend

### `backend/app/sources/column_mapping.py` (modified)

Existing `ColumnMapping` dataclass fields become optional for the 4 previously-required ones
(`name`/`wholesale_price`/`ean`/`category` go from `str` to `str | None`; `sku` was already
`str | None`). Existing `detect_column_mapping` (raises `ColumnMappingError` on any unresolved
required field) is unchanged — still used by any direct `POST /scans` call that supplies no mapping
override.

New sibling function:

```python
def detect_column_mapping_partial(header: list[str]) -> ColumnMapping:
    """Like detect_column_mapping, but never raises — an unresolved required
    field becomes None instead of raising ColumnMappingError, so the caller
    can surface it as "pick manually" instead of failing outright."""
```

### `backend/app/sources/csv_preview.py` (new)

```python
@dataclass(frozen=True)
class CsvPreview:
    headers: list[str]
    mapping: ColumnMapping              # None on any field that couldn't be resolved
    sample_rows: list[dict[str, str]]   # first 10 raw rows, all original CSV columns
    total_rows: int
    parsed_count: int                   # rows that became a valid Product
    warnings: list[str]                 # first 20
    warning_count: int                  # true total, may exceed len(warnings)

def build_csv_preview(
    csv_bytes: bytes, tenant_id: str, mapping_override: ColumnMapping | None
) -> CsvPreview: ...
```

`mapping_override` carries whatever the caller already knows (e.g. the user has picked 3 of 4
fields so far) — any field left `None` in it triggers `detect_column_mapping_partial`'s guess for
just that field, not the whole mapping. If, after combining override + auto-detection, all 4
required fields are resolved, `build_csv_preview` calls
`CsvCatalogSource(csv_bytes, tenant_id, column_mapping=mapping).fetch_products()` for
`parsed_count`/`warnings`/`warning_count` (from the source's own `.warnings` list) and computes
`total_rows` by counting CSV data rows independently (via `csv.DictReader`, the same dialect/encoding
detection `CsvCatalogSource` already uses). If any required field is still unresolved, parsing is
skipped entirely (`parsed_count=0`, `warnings=[]`, `warning_count=0`) — but `headers`/`sample_rows`
are still returned so the user has something to choose columns from.

### `backend/app/scans/api.py` (modified)

New endpoint:

```
POST /csv/preview
  multipart: file, name_column?, wholesale_price_column?, ean_column?,
             category_column?, sku_column?
  -> CsvPreview as JSON
```

400 only on `EmptyCsvError` (no header row at all — nothing to preview). Column-detection gaps are
never an error here, per the Decisions table above.

`POST /scans` gains the same 5 optional form fields (`Form(None)`, all strings). Validation rule:
either **all four** of `name_column`/`wholesale_price_column`/`ean_column`/`category_column` are
supplied together, or **none** of them are — a partial subset is rejected with 400 ("provide all of
name_column/wholesale_price_column/ean_column/category_column, or none"). This matters because
`CsvCatalogSource` would otherwise silently look up a nonexistent dict key for any field left as
`None` in a real `ColumnMapping`, producing empty names/prices for every row instead of an error.
`sku_column` may be supplied independently of that group (it's optional in `ColumnMapping` either
way). When the four are supplied, they're assembled into a complete `ColumnMapping` and passed to
`create_scan` (new optional `column_mapping: ColumnMapping | None` parameter, threaded straight into
`CsvCatalogSource(..., column_mapping=...)` in `orchestration.py`). When none are supplied, behavior
is unchanged — `CsvCatalogSource` auto-detects via the existing, raising `detect_column_mapping`,
preserving backward compatibility with every existing `POST /scans` test and caller. In practice the
frontend will always supply all 4 required fields, since `MappingStep` blocks "Dalej" until they're
filled — the "none supplied" fallback path exists for direct API/test callers only.

## Frontend

### `App.tsx`

`WizardStep` gains `'mapping'`, inserted between `'upload'` and `'scope'`. Wizard state gains
`columnMapping` (the confirmed mapping), threaded into `ScopeEstimateStep`.

### `frontend/src/api/`

`types.ts` gains `ColumnMappingValue` (`{ name: string | null; wholesalePrice: string | null; ean:
string | null; category: string | null; sku: string | null }`) and `CsvPreview` (mirroring the
backend response field-for-field). `client.ts` gains `getCsvPreview(file: File, mappingOverride?:
ColumnMappingValue): Promise<CsvPreview>` and `createScan`'s signature grows an optional
`columnMapping` parameter, appended to the existing `FormData` construction as the same 5 field
names the backend expects.

### `frontend/src/steps/MappingStep.tsx` (new)

1. On mount: calls `getCsvPreview(file)` with no override (pure auto-detection).
2. **Mapping card** — continuation of `ReportStep`'s grouped-card pattern (`rounded-2xl`, hairline
   row dividers): 5 rows (Nazwa, Cena hurtowa, EAN, Kategoria, SKU *(opcjonalne)*), each a `<select>`
   populated from `CsvPreview.headers` plus a blank option. Initial selected value is whatever
   `CsvPreview.mapping` resolved for that field (blank if `null`).
3. **"Odśwież podgląd" button** — explicit, not per-selection — re-calls `getCsvPreview(file,
   currentSelections)` with the user's current dropdown choices.
4. **Stats/warnings** — "`parsed_count` / `total_rows` wierszy sparsowanych poprawnie", then the
   (up to 20) warnings as a list, with "...i `warning_count - 20` więcej" when truncated.
5. **Sample-rows table** — hairline table (same visual pattern as Report's category table): columns
   = `CsvPreview.headers`, rows = `CsvPreview.sample_rows` (up to 10).
6. **"Dalej"** — disabled until all 4 required dropdowns (not SKU) have a non-blank selection. On
   click: the confirmed mapping is handed up to `App.tsx`, wizard advances to `'scope'`.

### `ScopeEstimateStep` (modified)

Gains a `columnMapping: ColumnMappingValue` prop, passed straight through to `createScan`'s new
parameter — no other behavior change.

## Error handling

- Empty CSV (no header row) at the preview step → 400, surfaced inline on `MappingStep` the same way
  `UploadStep`'s failures are today (the user would need to pick a different file — no column
  dropdowns to show).
- A `POST /scans` call reaching the backend with an incomplete mapping (shouldn't happen through the
  UI, since "Dalej" is blocked, but possible via direct API use) falls through to
  `CsvCatalogSource`'s own auto-detect-and-raise path if no override was given, or raises
  `ColumnMappingError` → existing 400 handling in `post_scans` if a partial override is given and
  `CsvCatalogSource` can't resolve the rest itself (existing behavior, unchanged).

## Testing

Backend: unit tests for `detect_column_mapping_partial` (mirroring `detect_column_mapping`'s
existing test cases, but asserting `None` instead of a raised exception for gaps); unit tests for
`build_csv_preview` covering full-auto-detection, partial-override, and unresolvable-field cases;
API tests for `POST /csv/preview` (200 with full mapping, 200 with partial/null mapping, 400 on
empty CSV) and `POST /scans` with an explicit mapping override (confirming it actually changes which
column is parsed as what, not just that the request succeeds) plus the 400 case for a partial subset
of the four required mapping fields. Frontend: component tests for
`MappingStep` covering initial auto-detected state, dropdown changes + "Odśwież podgląd" triggering
a new `getCsvPreview` call with the right fields, "Dalej" disabled/enabled logic, and the warning-list
truncation display.

## Out of scope for this phase

- Saving/remembering a mapping across uploads for the same supplier (every upload starts from fresh
  auto-detection).
- Detecting or correcting anything beyond the 5 existing fields (name/price/EAN/category/SKU) — no
  new product attributes.
- Client-side CSV parsing of any kind (stays entirely backend, per the project's standing rule that
  no domain logic lives in the frontend).
