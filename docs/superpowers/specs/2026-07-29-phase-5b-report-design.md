# Phase 5b — Report screen + backend margin aggregation — design spec

Status: **approved** (2026-07-29, via interactive brainstorming).

## Context

Phases 0–5a (see `2026-07-28-is-it-worth-it-design.md` and the phase 3/4/5a specs) built the full
pipeline up to a live-progress scan: CSV upload → column mapping → scope/estimate → price discovery
via Perplexity → SQLite-cached offers. What's missing is the actual payoff of the product: turning
those cached offers into a margin verdict. `calculate_margin`/`calculate_margin_matrix`
(`backend/app/pricing/margin.py`) have existed since Phase 0–2 as pure, fully-tested functions but
have never been wired to any data or any endpoint. This phase wires them up and adds the Report
screen — the last screen in the wizard (`Upload → Scope+Estimate → Progress → Report`).

## Key finding that shapes this design

`CostConfig` (commission %, shipping cost, VAT %, returns %) does not affect the scan itself in any
way — it is purely a report-time parameter over data that's already sitting in `scan_products`. This
means cost assumptions don't need to be decided before spending money on Perplexity queries, and can
be changed after the fact without re-scanning. The whole design follows from taking that seriously:
report computation is a pure, on-demand transformation over already-persisted data, parameterized by
whatever cost assumptions the user currently has dialed in.

## Decisions

| Topic | Decision |
|---|---|
| Where cost config is entered | On the Report screen itself, recomputed on demand (explicit "Przelicz" action, not live-per-keystroke — see Scale below) |
| Cost config persistence | Frontend-only, via `localStorage`; no backend storage, no per-scan snapshot |
| Scenario percentages | Stay fixed at the existing `SCENARIO_ADJUSTMENTS` (−10/−5/0/+5%) for this phase; not user-configurable yet |
| Excluded products (no offer / anomaly / currency mismatch / not yet checked) | Excluded from averages, always visible as counts; never silently folded into an average |
| Currency mismatch (`offer.currency != product.currency`) | Treated as its own exclusion reason in this phase — no conversion logic is written; a mismatched offer is flagged and left out of margin math rather than silently computed as if same-currency |
| Scenario matrix shape | One global matrix (not per-category): 4 columns, each showing avg margin % and count of profitable products, over all `computable` products |
| Category table | Per-category breakdown at the 0% reference scenario: computable count, excluded count, avg margin % |
| Product drill-down at scale | Backend-side pagination/filtering/sorting — the target catalog is ~115k rows; loading everything into the browser is not viable |
| Visual direction | Apple-inspired dashboard treatment: a single "verdict" numeral as the page's signature element, a Settings.app-style grouped card for the cost form, card-based scenario matrix, hairline-rule tables, table→card collapse on mobile. Existing `slate-950`/`emerald-600` palette kept for continuity with Upload/Scope/Progress — the differentiation is structural (numerals, grouping, spacing), not a new color scheme. See "Visual design" below. |

## Backend

### `backend/app/reports/` (new module, sibling to `scans/`, `providers/`, `pricing/`)

**`evaluate.py`** — the single source of truth for "is this product's offer usable, and if so what's
its margin":

```python
class ExclusionReason(str, Enum):
    NOT_CHECKED = "not_checked"        # status still PENDING (only possible on a `failed` scan)
    NO_OFFER = "no_offer"              # offer is None (provider found nothing valid)
    CURRENCY_MISMATCH = "currency_mismatch"  # offer.currency != product.currency
    ANOMALY = "anomaly"                # detect_anomaly(...) returned a flag

@dataclass(frozen=True)
class ProductEvaluation:
    record: ScanProductRecord
    computable: bool
    exclusion_reason: ExclusionReason | None
    anomaly_flag: AnomalyFlag | None       # set alongside ANOMALY, for display
    margin_matrix: tuple[MarginResult, ...] | None  # set iff computable

def evaluate_record(record: ScanProductRecord, cost_config: CostConfig) -> ProductEvaluation: ...
```

Check order: `NOT_CHECKED` (status != DONE) → `NO_OFFER` (offer is None) → `CURRENCY_MISMATCH` →
`ANOMALY` (via the existing, already-tested `detect_anomaly`) → otherwise compute
`calculate_margin_matrix(record.product.wholesale_price, record.offer.price, cost_config)`.

Both aggregation and the product list below call this same function per record — there is exactly
one place that decides whether a product counts.

**`aggregate.py`** — `build_summary(records: Iterable[ScanProductRecord], cost_config: CostConfig) ->
ReportSummary`. One pass over all records, calling `evaluate_record` on each and accumulating:

```python
@dataclass(frozen=True)
class ReportCounts:
    total: int
    computable: int
    not_checked: int
    no_offer: int
    currency_mismatch: int
    anomaly: int

@dataclass(frozen=True)
class CategoryRow:
    category: str
    computable_count: int
    excluded_count: int
    avg_margin_pct: Decimal | None  # at scenario 0%; None if computable_count == 0

@dataclass(frozen=True)
class ScenarioRow:
    scenario_pct: Decimal
    avg_margin_pct: Decimal | None  # None if no computable products at all
    profitable_count: int           # margin > 0 at this scenario

@dataclass(frozen=True)
class ReportSummary:
    counts: ReportCounts
    category_table: tuple[CategoryRow, ...]
    scenario_matrix: tuple[ScenarioRow, ...]
```

**`products.py`** — `list_product_rows(records, cost_config, *, category=None, status=None, sort=...,
page, page_size) -> ProductPage`. Runs `evaluate_record` over all records, filters by category and/or
`status` (matches `computable` or one `ExclusionReason` value), sorts (`category_name` [default],
`margin_asc`, `margin_desc`, `name`), then slices to the requested page. Each row exposes the full
`ProductEvaluation` plus the underlying `OfferResult` fields needed for drill-down display (`seller`,
`source_url`, `delivery_days`, `confidence`, `citations`).

### `ScanStore` (`backend/app/scans/store.py`)

New method `list_all(scan_id: str) -> list[ScanProductRecord]`: like `list_pending`, but without the
`status = PENDING` filter, and — unlike `list_pending`'s row mapper, which never reads the `offer_*`
columns because pending rows never have them — this one *does* parse `offer_*` columns into an
`OfferResult` whenever `status = DONE`. Needs its own row-mapper (`_row_to_record_with_offer` or
similar), not a reuse of `_row_to_record`.

### API (`backend/app/reports/api.py`, mounted in `main.py` alongside the scans router)

```
GET /scans/{scan_id}/report/summary
  ?commission_pct=&shipping_cost=&vat_pct=&returns_pct=
  -> ReportSummary as JSON (Decimals as strings, matching the existing `estimate.cost_usd_*` convention)

GET /scans/{scan_id}/report/products
  ?commission_pct=&shipping_cost=&vat_pct=&returns_pct=
  &category=&status=&sort=&page=&page_size=
  -> paginated product rows
```

Both endpoints:
- 404 if the scan doesn't exist.
- 400 if `scan.status` is `estimated` or `running` — a report only makes sense once a scan has
  actually run to some terminal state (`done` or `failed`; `failed` still yields a partial report,
  with leftover `PENDING` rows counted as `not_checked`).
- 400 on missing/negative cost values, validated the same way `post_scans` validates its own
  parameters today.
- `commission_pct`/`shipping_cost`/`vat_pct`/`returns_pct` are read as query strings and parsed to
  `Decimal` by hand in the handler — never declared as `float` FastAPI params — consistent with how
  money is handled everywhere else in this codebase.

## Frontend

### `App.tsx`

Add `'report'` to `WizardStep`. `ProgressStep` gains an `onDone: (scanId: string) => void` prop,
called once `scan.status` reaches `done` or `failed`. Rather than auto-navigating, `ProgressStep`
shows a "Zobacz raport" button once terminal (for both `done` and `failed` — a partial report is
still useful) that triggers the transition.

### `frontend/src/api/`

`types.ts` gains `CostConfigInput`, `ReportCounts`, `CategoryRow`, `ScenarioRow`, `ReportSummary`,
`ExclusionReason`, `ProductRow`, `ProductPage` — mirroring the backend response shapes exactly, same
hand-maintained-mirror approach already used for the rest of `api/types.ts`.

`client.ts` gains `getReportSummary(scanId, costConfig)` and `getReportProducts(scanId, costConfig,
params)`.

### `frontend/src/steps/ReportStep.tsx` (new)

Structure, top to bottom:

1. **Verdict** — the page's signature element: one large tabular numeral (e.g. `+18.4%`), the average
   margin % at the 0% reference scenario, colored by sign (`emerald` positive, `rose` negative), with
   a small caption underneath ("X / Y produktów rentownych"). This is the direct answer to "is it
   worth it" and is the first thing seen, before any table.
2. **Cost config card** — a single `rounded-2xl border border-slate-800` card, `divide-y
   divide-slate-800/60` rows, each row: label left, numeric input right (commission %, shipping,
   VAT %, returns %). A "Przelicz" button below the card triggers both report requests. Initial
   values loaded from `localStorage` (key `isItWorthIt.costConfig`); written back to `localStorage`
   after every successful recalculation.
3. **Exclusion counts bar** — a row of quiet pill/chip elements (`rounded-full bg-slate-900
   text-slate-400`), one per non-zero count (`no_offer`, `anomaly`, `currency_mismatch`, and
   `not_checked` only when > 0, i.e. only for a `failed` scan). Colored `amber-400` when count > 0,
   otherwise not shown at all — never an alarming red block, just information.
4. **Scenario matrix** — 4 cards in a responsive grid (`grid-cols-1 sm:grid-cols-2 lg:grid-cols-4`):
   eyebrow label (`−10%` etc.), large avg-margin-% numeral colored by sign, small "X rentownych"
   caption.
5. **Category table** — hairline dividers (`border-slate-800/60`), right-aligned `tabular-nums`
   figures, one row per category: name, computable count, excluded count, avg margin %.
6. **Product drill-down** — paginated table (desktop) that collapses to a stacked card list at the
   `md` breakpoint (mobile). Controls: category filter, status filter (matches `ExclusionReason` or
   "computable"), sort (margin asc/desc/name), pager. Expanding a row/card reveals: seller, a
   clickable `source_url`, delivery days, confidence, the anomaly flag if present, and the full
   4-scenario margin breakdown for that one product.

**Recompute is explicit, not per-keystroke**: the cost-config form updates local component state as
the user types; nothing hits the network until "Przelicz" is pressed. This matters at catalog scale —
the summary endpoint does an O(n) Python pass over up to ~115k rows per request (typically well under
a couple of seconds, but not something to fire on every keystroke).

**Scale**: no product list is ever loaded in full into the browser; the product table always goes
through the paginated endpoint. Category table and scenario matrix are small, fixed-size responses
(bounded by category count and 4 scenarios respectively) even though computing them requires a full
server-side pass.

### Visual design

Existing `slate-950` background / `slate-100` text / `emerald-600` accent is kept for continuity with
Upload, Scope+Estimate, and Progress — introducing a new palette for one screen inside the same wizard
would read as inconsistent, not distinctive. The Apple-inspired direction the user asked for is
expressed structurally instead: a single big verdict numeral as the page's one signature element
(rather than a marketing-style hero), a Settings.app-style grouped list for the cost-config card,
card-based (not table-based) presentation for the 4 scenarios, hairline rules instead of boxed
borders for the category table, and a table-that-becomes-cards responsive pattern for the
product drill-down. Signal colors: margin-positive reuses the existing `emerald` accent (no second
green introduced), margin-negative uses `rose-400`, exclusion/anomaly chips use `amber-400` —
consistent with the amber warning style `ScopeEstimateStep` already uses for CSV parse warnings. Cards
on this screen use `rounded-2xl` (softer than the `rounded-md` of earlier, simpler steps), reflecting
that this is the densest, most-lived-in screen in the wizard and warrants the most deliberate
treatment. Motion is limited to a single subtle fade-in on the verdict numeral at load — no other
animation.

## Error handling

- Requesting a report for a scan still `estimated`/`running` → 400 from the backend; the frontend
  never constructs this request in practice (the "Zobacz raport" button only appears once terminal),
  but the backend still guards it since it's a public endpoint.
- Invalid/negative cost values → 400, surfaced as an inline error near the cost-config card (same
  pattern as the existing `error` state in `ScopeEstimateStep`).
- Empty scan (0 products, or 0 computable products) → verdict numeral shows an explicit "brak danych
  do policzenia" state instead of `NaN`/`0%`, category table and scenario matrix render their
  zero-count state without crashing.

## Testing

Backend: unit tests for `evaluate_record` covering each `ExclusionReason` branch and the
happy/computable path; unit tests for `build_summary` and `list_product_rows` against a hand-built set
of `ScanProductRecord`s covering a mix of computable/excluded/mixed-category data; API tests for both
endpoints covering the 400s (wrong scan status, bad cost values) and a happy path against a seeded
`ScanStore`. Frontend: component tests for `ReportStep` covering the recompute flow, empty/zero
states, and the exclusion-chip visibility logic (matching the existing Vitest + RTL setup from Phase
5a).

## Out of scope for this phase

- Configurable scenario percentages (stays fixed at −10/−5/0/+5%).
- Currency conversion (mismatches are flagged and excluded, not converted).
- Backend-side persistence of cost config (frontend `localStorage` only).
- A "past scans" browsing/history screen — Report is only reachable via the just-run wizard flow, not
  as a standalone lookup by scan ID.
- CSV/export of the report (out of scope until requested).
