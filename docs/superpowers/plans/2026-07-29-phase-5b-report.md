# Phase 5b — Report Screen + Backend Margin Aggregation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the already-existing, already-tested `calculate_margin_matrix` to real scan data:
add a backend `reports/` module that turns a scan's cached offers into a margin verdict, two
paginated/filterable read endpoints, and a new `ReportStep` screen that closes the wizard
(`Upload → Scope+Estimate → Progress → Report`).

**Architecture:** One pure evaluation function (`evaluate_record`) decides, per product, whether
its offer is usable and if so what its margin is at each of the 4 fixed scenarios. Two callers
build on top of it: `build_summary` (one aggregation pass → verdict/scenario-matrix/category-table)
and `list_product_rows` (filter/sort/paginate → per-product drill-down). Both are exposed as GET
endpoints that accept `CostConfig` as query parameters and recompute from already-persisted
`scan_products` rows on every call — nothing about cost assumptions is ever written to the
database. The frontend mirrors this: a `ReportStep` holds the cost-config form (persisted only to
`localStorage`), triggers an explicit recalculation, and renders the verdict, scenario matrix,
category table, and a paginated product table with expandable rows.

**Tech Stack:** FastAPD + `Decimal`-only money math (backend, matching the whole codebase's existing
convention), React 19 + TypeScript + Tailwind (frontend, matching Phase 5a). No new dependencies
anywhere in this plan.

## Global Constraints

- Money is always `Decimal` server-side, never `float` — `commission_pct`/`shipping_cost`/
  `vat_pct`/`returns_pct` are read as raw query strings and parsed to `Decimal` by hand in the API
  layer, never declared as FastAPI `float` params.
- The scenario percentages stay fixed at `SCENARIO_ADJUSTMENTS` from `app/pricing/margin.py`
  (−10/−5/0/+5%) — not configurable in this phase.
- Every product lands in exactly one bucket: `computable`, or one `ExclusionReason` of
  `NOT_CHECKED`, `NO_OFFER`, `CURRENCY_MISMATCH`, `ANOMALY`. Excluded products are never silently
  folded into an average — they're always visible as a count.
- `GET /scans/{id}/report/summary` and `GET /scans/{id}/report/products` both 400 unless
  `scan.status` is `done` or `failed` (a report only makes sense once a scan has run to some
  terminal state).
- The product drill-down is always paginated server-side — the target catalog is ~115k rows; no
  code path loads a full product list into the browser.
- Cost config lives only in the browser (`localStorage` key `isItWorthIt.costConfig`) — no backend
  storage, no per-scan snapshot. Recalculation is explicit (a "Przelicz" button), never triggered
  per-keystroke, because the summary endpoint does an O(n) pass over up to ~115k rows per call.
- Visual direction (see the approved design spec): keep the existing `slate-950`/`slate-100`/
  `emerald-600` palette; margin-negative uses `rose-400`; exclusion/anomaly chips use `amber-400`;
  cards use `rounded-2xl`; the verdict numeral is the page's one signature element; motion is
  limited to a single fade-in on that numeral (not implemented as a literal requirement in this
  plan's tests — treat it as a nice-to-have `className` addition, not a blocking assertion).
- The Vite dev-server proxy already forwards any path starting with `/scans` (see
  `frontend/vite.config.ts`'s `server.proxy` from Phase 5a) — `/scans/{id}/report/summary` and
  `/scans/{id}/report/products` are covered by the existing `'/scans': 'http://localhost:8000'`
  entry. No proxy config change needed in this plan.
- Design spec: `docs/superpowers/specs/2026-07-29-phase-5b-report-design.md`. Read it if any task
  description here feels ambiguous — it's the source of truth this plan was derived from.

---

## File Structure

- Create: `backend/app/reports/__init__.py` (empty)
- Create: `backend/app/reports/evaluate.py` — `ExclusionReason`, `ProductEvaluation`,
  `evaluate_record`.
- Create: `backend/tests/reports/__init__.py` (empty)
- Test: `backend/tests/reports/test_evaluate.py`
- Modify: `backend/app/scans/store.py` — add `ScanStore.list_all`.
- Modify: `backend/tests/scans/test_store.py` — append tests for `list_all`.
- Create: `backend/app/reports/aggregate.py` — `ReportCounts`, `CategoryRow`, `ScenarioRow`,
  `ReportSummary`, `build_summary`.
- Test: `backend/tests/reports/test_aggregate.py`
- Create: `backend/app/reports/products.py` — `ProductPage`, `list_product_rows`, `VALID_SORTS`,
  `VALID_STATUSES`.
- Test: `backend/tests/reports/test_products.py`
- Create: `backend/app/reports/api.py` — the two report endpoints.
- Modify: `backend/app/main.py` — mount the reports router.
- Test: `backend/tests/reports/test_api.py`
- Modify: `frontend/src/api/types.ts` — add `CostConfigInput`, `ExclusionReason`, `ReportCounts`,
  `CategoryRow`, `ScenarioRow`, `ReportSummary`, `MarginResult`, `ProductOffer`, `ProductRow`,
  `ProductPage`.
- Modify: `frontend/src/api/client.ts` — add `getReportSummary`, `getReportProducts`.
- Modify: `frontend/src/api/client.test.ts` — append tests for both.
- Create: `frontend/src/steps/ReportStep.tsx` — verdict, cost-config card, exclusion chips,
  scenario matrix, category table (Task 7), then extended with the product drill-down (Task 8).
- Test: `frontend/src/steps/ReportStep.test.tsx`
- Modify: `frontend/src/steps/ProgressStep.tsx` — add `onDone` prop and a "Zobacz raport" button.
- Modify: `frontend/src/steps/ProgressStep.test.tsx` — update existing renders, add a new test.
- Modify: `frontend/src/App.tsx` — wire in the `'report'` step.
- Modify: `frontend/src/App.test.tsx` — add a full upload→report walkthrough test.

---

## Task 1: `evaluate_record` — the single source of truth for "does this product count"

**Files:**
- Create: `backend/app/reports/__init__.py`
- Create: `backend/app/reports/evaluate.py`
- Create: `backend/tests/reports/__init__.py`
- Test: `backend/tests/reports/test_evaluate.py`

**Interfaces:**
- Consumes: `CostConfig`, `MarginResult`, `calculate_margin_matrix` from
  `app.pricing.margin` (existing); `AnomalyFlag`, `detect_anomaly` from `app.providers.anomaly`
  (existing); `ProductStatus`, `ScanProductRecord` from `app.scans.models` (existing).
- Produces: `ExclusionReason` (str enum: `NOT_CHECKED`, `NO_OFFER`, `CURRENCY_MISMATCH`,
  `ANOMALY`), `ProductEvaluation` (frozen dataclass: `record: ScanProductRecord`,
  `computable: bool`, `exclusion_reason: ExclusionReason | None`,
  `anomaly_flag: AnomalyFlag | None`, `margin_matrix: tuple[MarginResult, ...] | None`),
  `evaluate_record(record: ScanProductRecord, cost_config: CostConfig) -> ProductEvaluation`.
  Used by Task 3's `build_summary` and Task 4's `list_product_rows`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/reports/__init__.py
```

```python
# backend/tests/reports/test_evaluate.py
from decimal import Decimal

from app.models.product import Product
from app.pricing.margin import CostConfig
from app.providers.anomaly import AnomalyFlag
from app.providers.base import OfferResult
from app.reports.evaluate import ExclusionReason, evaluate_record
from app.scans.models import ProductStatus, ScanProductRecord

COST_CONFIG = CostConfig(
    commission_pct=Decimal("0.10"),
    shipping_cost=Decimal("15.00"),
    vat_pct=Decimal("0.23"),
    returns_pct=Decimal("0.02"),
)


def _make_product(**overrides) -> Product:
    defaults = dict(
        tenant_id="t1", source="csv", external_id="1", variant_id=None,
        name="Test Product", ean="5901234123457",
        wholesale_price=Decimal("40.00"), currency="PLN", category="Elektronika",
    )
    defaults.update(overrides)
    return Product(**defaults)


def _make_offer(**overrides) -> OfferResult:
    defaults = dict(
        price=Decimal("100.00"), currency="PLN", seller="Shop",
        source_url="https://example.com/x", delivery_days=2,
        confidence=0.9, citations=("https://example.com/x",), raw_response="{}",
    )
    defaults.update(overrides)
    return OfferResult(**defaults)


def _make_record(*, status=ProductStatus.DONE, offer=None, **product_overrides) -> ScanProductRecord:
    return ScanProductRecord(
        id=1, scan_id="scan-1", product=_make_product(**product_overrides),
        status=status, was_stale=False, offer=offer,
    )


def test_computable_product_gets_full_four_scenario_margin_matrix():
    record = _make_record(offer=_make_offer())

    evaluation = evaluate_record(record, COST_CONFIG)

    assert evaluation.computable is True
    assert evaluation.exclusion_reason is None
    assert evaluation.anomaly_flag is None
    assert evaluation.margin_matrix is not None
    assert len(evaluation.margin_matrix) == 4
    assert evaluation.margin_matrix[2].scenario_pct == Decimal("0.00")


def test_not_checked_when_status_is_pending():
    record = _make_record(status=ProductStatus.PENDING, offer=None)

    evaluation = evaluate_record(record, COST_CONFIG)

    assert evaluation.computable is False
    assert evaluation.exclusion_reason == ExclusionReason.NOT_CHECKED
    assert evaluation.margin_matrix is None


def test_no_offer_when_done_but_offer_is_none():
    record = _make_record(status=ProductStatus.DONE, offer=None)

    evaluation = evaluate_record(record, COST_CONFIG)

    assert evaluation.exclusion_reason == ExclusionReason.NO_OFFER


def test_currency_mismatch_when_offer_currency_differs_from_product_currency():
    record = _make_record(offer=_make_offer(currency="EUR"))

    evaluation = evaluate_record(record, COST_CONFIG)

    assert evaluation.exclusion_reason == ExclusionReason.CURRENCY_MISMATCH
    assert evaluation.margin_matrix is None


def test_anomaly_flag_set_for_below_wholesale_offer():
    record = _make_record(wholesale_price=Decimal("200.00"), offer=_make_offer(price=Decimal("100.00")))

    evaluation = evaluate_record(record, COST_CONFIG)

    assert evaluation.exclusion_reason == ExclusionReason.ANOMALY
    assert evaluation.anomaly_flag == AnomalyFlag.BELOW_WHOLESALE


def test_anomaly_flag_set_for_low_confidence_offer():
    record = _make_record(offer=_make_offer(confidence=0.2))

    evaluation = evaluate_record(record, COST_CONFIG)

    assert evaluation.exclusion_reason == ExclusionReason.ANOMALY
    assert evaluation.anomaly_flag == AnomalyFlag.LOW_CONFIDENCE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/reports/test_evaluate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.reports'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/reports/__init__.py
```

```python
# backend/app/reports/evaluate.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.pricing.margin import CostConfig, MarginResult, calculate_margin_matrix
from app.providers.anomaly import AnomalyFlag, detect_anomaly
from app.scans.models import ProductStatus, ScanProductRecord


class ExclusionReason(str, Enum):
    NOT_CHECKED = "not_checked"
    NO_OFFER = "no_offer"
    CURRENCY_MISMATCH = "currency_mismatch"
    ANOMALY = "anomaly"


@dataclass(frozen=True)
class ProductEvaluation:
    record: ScanProductRecord
    computable: bool
    exclusion_reason: ExclusionReason | None
    anomaly_flag: AnomalyFlag | None
    margin_matrix: tuple[MarginResult, ...] | None


def _excluded(record: ScanProductRecord, reason: ExclusionReason, anomaly_flag: AnomalyFlag | None = None) -> ProductEvaluation:
    return ProductEvaluation(
        record=record, computable=False, exclusion_reason=reason,
        anomaly_flag=anomaly_flag, margin_matrix=None,
    )


def evaluate_record(record: ScanProductRecord, cost_config: CostConfig) -> ProductEvaluation:
    if record.status != ProductStatus.DONE:
        return _excluded(record, ExclusionReason.NOT_CHECKED)
    if record.offer is None:
        return _excluded(record, ExclusionReason.NO_OFFER)
    if record.offer.currency != record.product.currency:
        return _excluded(record, ExclusionReason.CURRENCY_MISMATCH)

    anomaly = detect_anomaly(record.offer, record.product.wholesale_price)
    if anomaly is not None:
        return _excluded(record, ExclusionReason.ANOMALY, anomaly_flag=anomaly)

    matrix = tuple(
        calculate_margin_matrix(record.product.wholesale_price, record.offer.price, cost_config)
    )
    return ProductEvaluation(
        record=record, computable=True, exclusion_reason=None,
        anomaly_flag=None, margin_matrix=matrix,
    )
```

`calculate_margin_matrix` can in principle raise `UndefinedMarginError` (zero sale price). In
practice this can't happen here: the provider layer (`app/providers/perplexity.py`'s
`_parse_response`) already rejects `price <= 0` before an offer is ever persisted, so `record.offer.price`
is always positive by the time it reaches this function. No exclusion reason is defined for it — if
it ever raised, that's a bug to surface, not a state to render.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/reports/test_evaluate.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/reports/__init__.py backend/app/reports/evaluate.py backend/tests/reports/__init__.py backend/tests/reports/test_evaluate.py
git commit -m "Add evaluate_record: the single source of truth for per-product report eligibility"
```

---

## Task 2: `ScanStore.list_all` — read every product row, including its offer

**Files:**
- Modify: `backend/app/scans/store.py`
- Modify: `backend/tests/scans/test_store.py`

**Interfaces:**
- Produces: `ScanStore.list_all(scan_id: str) -> list[ScanProductRecord]` — unlike
  `list_pending`, returns every row regardless of status, and (unlike `list_pending`'s row mapper,
  which never reads the `offer_*` columns because pending rows never have them) parses `offer_*`
  columns into an `OfferResult` whenever `status == DONE`. Used by Task 5's report endpoints.

- [ ] **Step 1: Write the failing test**

Append to the end of `backend/tests/scans/test_store.py` (it already defines `_make_product` and
`_make_offer` helpers at module scope — reuse them, don't redefine):

```python
def test_list_all_returns_both_pending_and_done_records_with_offer(tmp_path):
    store = ScanStore(tmp_path / "app.sqlite3")
    products = [_make_product(external_id="1"), _make_product(external_id="2")]
    estimate = estimate_cost(cache_misses=2, stale_count=0, max_concurrency=5)
    scan_id = store.create_scan(
        scope_type="full", sample_per_category=None, market="PL", max_delivery_days=5,
        max_concurrency=5, staleness_threshold_days=14,
        products=products, stale_eans=(), estimate=estimate,
        overlapping_count=0, stale_count=0,
    )
    pending = store.list_pending(scan_id)
    record_to_finish = next(r for r in pending if r.product.external_id == "1")
    offer = _make_offer()
    store.mark_done(record_to_finish.id, offer)

    all_records = store.list_all(scan_id)

    assert len(all_records) == 2
    by_external_id = {r.product.external_id: r for r in all_records}
    assert by_external_id["1"].status == ProductStatus.DONE
    assert by_external_id["1"].offer == offer
    assert by_external_id["2"].status == ProductStatus.PENDING
    assert by_external_id["2"].offer is None
    store.close()


def test_list_all_reads_a_negative_result_offer_as_none(tmp_path):
    store = ScanStore(tmp_path / "app.sqlite3")
    products = [_make_product(external_id="1")]
    estimate = estimate_cost(cache_misses=1, stale_count=0, max_concurrency=5)
    scan_id = store.create_scan(
        scope_type="full", sample_per_category=None, market="PL", max_delivery_days=5,
        max_concurrency=5, staleness_threshold_days=14,
        products=products, stale_eans=(), estimate=estimate,
        overlapping_count=0, stale_count=0,
    )
    record = store.list_pending(scan_id)[0]
    store.mark_done(record.id, None)

    all_records = store.list_all(scan_id)

    assert all_records[0].status == ProductStatus.DONE
    assert all_records[0].offer is None
    store.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/scans/test_store.py -v -k list_all`
Expected: FAIL with `AttributeError: 'ScanStore' object has no attribute 'list_all'`

- [ ] **Step 3: Write minimal implementation**

Add to `backend/app/scans/store.py`, directly after the existing `list_pending` method (which ends
just before `_row_to_record`):

```python
    def list_all(self, scan_id: str) -> list[ScanProductRecord]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, tenant_id, source, external_id, variant_id, name, ean,
                       wholesale_price, currency, category, status, was_stale,
                       offer_price, offer_currency, offer_seller, offer_source_url,
                       offer_delivery_days, offer_confidence, offer_citations, offer_raw_response
                FROM scan_products WHERE scan_id = ?
                """,
                (scan_id,),
            ).fetchall()
        return [self._row_to_record_with_offer(scan_id, row) for row in rows]
```

And add this row-mapper right after the existing `_row_to_record` method (which only handles
pending rows and never reads the `offer_*` columns):

```python
    def _row_to_record_with_offer(self, scan_id: str, row: tuple) -> ScanProductRecord:
        (
            record_id, tenant_id, source, external_id, variant_id, name, ean,
            wholesale_price, currency, category, status, was_stale,
            offer_price, offer_currency, offer_seller, offer_source_url,
            offer_delivery_days, offer_confidence, offer_citations, offer_raw_response,
        ) = row
        product = Product(
            tenant_id=tenant_id, source=source, external_id=external_id,
            variant_id=variant_id, name=name, ean=ean,
            wholesale_price=Decimal(wholesale_price), currency=currency, category=category,
        )
        offer = None
        if offer_price is not None:
            offer = OfferResult(
                price=Decimal(offer_price), currency=offer_currency, seller=offer_seller,
                source_url=offer_source_url, delivery_days=offer_delivery_days,
                confidence=offer_confidence, citations=tuple(json.loads(offer_citations)),
                raw_response=offer_raw_response,
            )
        return ScanProductRecord(
            id=record_id, scan_id=scan_id, product=product,
            status=ProductStatus(status), was_stale=bool(was_stale), offer=offer,
        )
```

`json` and `Decimal` are already imported at the top of `store.py` (used by `_mark` and the
existing row mapper) — no new imports needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/scans/test_store.py -v`
Expected: PASS (all tests in the file, including the 2 new ones)

- [ ] **Step 5: Commit**

```bash
git add backend/app/scans/store.py backend/tests/scans/test_store.py
git commit -m "Add ScanStore.list_all: read every scan_products row, offer included"
```

---

## Task 3: `build_summary` — verdict, scenario matrix, category table

**Files:**
- Create: `backend/app/reports/aggregate.py`
- Test: `backend/tests/reports/test_aggregate.py`

**Interfaces:**
- Consumes: `ExclusionReason`, `evaluate_record` from Task 1's `app.reports.evaluate`;
  `CostConfig`, `SCENARIO_ADJUSTMENTS` from `app.pricing.margin`; `ScanProductRecord` from
  `app.scans.models`.
- Produces: `ReportCounts` (frozen dataclass: `total`, `computable`, `not_checked`, `no_offer`,
  `currency_mismatch`, `anomaly` — all `int`), `CategoryRow` (`category: str`,
  `computable_count: int`, `excluded_count: int`, `avg_margin_pct: Decimal | None`),
  `ScenarioRow` (`scenario_pct: Decimal`, `avg_margin_pct: Decimal | None`,
  `profitable_count: int`), `ReportSummary` (`counts: ReportCounts`,
  `category_table: tuple[CategoryRow, ...]`, `scenario_matrix: tuple[ScenarioRow, ...]`),
  `build_summary(records: Iterable[ScanProductRecord], cost_config: CostConfig) -> ReportSummary`.
  Used by Task 5's `GET /scans/{id}/report/summary`.

Invariant: `counts.total == counts.computable + counts.not_checked + counts.no_offer +
counts.currency_mismatch + counts.anomaly`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/reports/test_aggregate.py
from decimal import Decimal

from app.models.product import Product
from app.pricing.margin import CostConfig, SCENARIO_ADJUSTMENTS, calculate_margin
from app.providers.base import OfferResult
from app.reports.aggregate import build_summary
from app.scans.models import ProductStatus, ScanProductRecord

COST_CONFIG = CostConfig(
    commission_pct=Decimal("0.10"),
    shipping_cost=Decimal("15.00"),
    vat_pct=Decimal("0.23"),
    returns_pct=Decimal("0.02"),
)


def _make_product(**overrides) -> Product:
    defaults = dict(
        tenant_id="t1", source="csv", external_id="1", variant_id=None,
        name="Test Product", ean="5901234123457",
        wholesale_price=Decimal("40.00"), currency="PLN", category="Elektronika",
    )
    defaults.update(overrides)
    return Product(**defaults)


def _make_offer(**overrides) -> OfferResult:
    defaults = dict(
        price=Decimal("100.00"), currency="PLN", seller="Shop",
        source_url="https://example.com/x", delivery_days=2,
        confidence=0.9, citations=(), raw_response="{}",
    )
    defaults.update(overrides)
    return OfferResult(**defaults)


def _make_record(record_id, *, status=ProductStatus.DONE, offer=None, **product_overrides) -> ScanProductRecord:
    return ScanProductRecord(
        id=record_id, scan_id="scan-1", product=_make_product(**product_overrides),
        status=status, was_stale=False, offer=offer,
    )


def test_build_summary_counts_and_buckets_by_exclusion_reason():
    records = [
        _make_record(1, offer=_make_offer(price=Decimal("100.00")), wholesale_price=Decimal("40.00"), category="Elektronika"),
        _make_record(2, offer=_make_offer(price=Decimal("100.00")), wholesale_price=Decimal("60.00"), category="Elektronika"),
        _make_record(3, status=ProductStatus.DONE, offer=None, category="Elektronika"),
        _make_record(4, offer=_make_offer(confidence=0.1), category="Dom"),
        _make_record(5, offer=_make_offer(currency="EUR"), category="Dom"),
        _make_record(6, status=ProductStatus.PENDING, offer=None, category="Dom"),
    ]

    summary = build_summary(records, COST_CONFIG)

    assert summary.counts.total == 6
    assert summary.counts.computable == 2
    assert summary.counts.no_offer == 1
    assert summary.counts.anomaly == 1
    assert summary.counts.currency_mismatch == 1
    assert summary.counts.not_checked == 1


def test_category_table_averages_only_computable_products_at_reference_scenario():
    records = [
        _make_record(1, offer=_make_offer(price=Decimal("100.00")), wholesale_price=Decimal("40.00"), category="Elektronika"),
        _make_record(2, offer=_make_offer(price=Decimal("100.00")), wholesale_price=Decimal("60.00"), category="Elektronika"),
        _make_record(3, status=ProductStatus.DONE, offer=None, category="Elektronika"),
        _make_record(4, status=ProductStatus.PENDING, offer=None, category="Dom"),
    ]

    summary = build_summary(records, COST_CONFIG)

    by_category = {row.category: row for row in summary.category_table}
    margin_a = calculate_margin(Decimal("40.00"), Decimal("100.00"), COST_CONFIG, Decimal("0.00")).margin_pct
    margin_b = calculate_margin(Decimal("60.00"), Decimal("100.00"), COST_CONFIG, Decimal("0.00")).margin_pct
    assert by_category["Elektronika"].computable_count == 2
    assert by_category["Elektronika"].excluded_count == 1
    assert by_category["Elektronika"].avg_margin_pct == (margin_a + margin_b) / 2
    assert by_category["Dom"].computable_count == 0
    assert by_category["Dom"].excluded_count == 1
    assert by_category["Dom"].avg_margin_pct is None


def test_scenario_matrix_is_global_across_all_computable_products():
    records = [
        _make_record(1, offer=_make_offer(price=Decimal("100.00")), wholesale_price=Decimal("40.00"), category="Elektronika"),
        _make_record(2, offer=_make_offer(price=Decimal("100.00")), wholesale_price=Decimal("60.00"), category="Dom"),
    ]

    summary = build_summary(records, COST_CONFIG)

    assert len(summary.scenario_matrix) == len(SCENARIO_ADJUSTMENTS)
    for row, scenario_pct in zip(summary.scenario_matrix, SCENARIO_ADJUSTMENTS):
        assert row.scenario_pct == scenario_pct
        margin_a = calculate_margin(Decimal("40.00"), Decimal("100.00"), COST_CONFIG, scenario_pct)
        margin_b = calculate_margin(Decimal("60.00"), Decimal("100.00"), COST_CONFIG, scenario_pct)
        assert row.avg_margin_pct == (margin_a.margin_pct + margin_b.margin_pct) / 2
        expected_profitable = sum(1 for m in (margin_a, margin_b) if m.margin > 0)
        assert row.profitable_count == expected_profitable


def test_scenario_matrix_avg_is_none_when_no_computable_products():
    records = [_make_record(1, status=ProductStatus.PENDING, offer=None)]

    summary = build_summary(records, COST_CONFIG)

    assert all(row.avg_margin_pct is None for row in summary.scenario_matrix)
    assert all(row.profitable_count == 0 for row in summary.scenario_matrix)


def test_build_summary_handles_empty_input():
    summary = build_summary([], COST_CONFIG)

    assert summary.counts.total == 0
    assert summary.category_table == ()
    assert all(row.avg_margin_pct is None for row in summary.scenario_matrix)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/reports/test_aggregate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.reports.aggregate'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/reports/aggregate.py
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from app.pricing.margin import CostConfig, SCENARIO_ADJUSTMENTS
from app.reports.evaluate import ExclusionReason, evaluate_record
from app.scans.models import ScanProductRecord

_REFERENCE_SCENARIO_INDEX = SCENARIO_ADJUSTMENTS.index(Decimal("0.00"))


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
    avg_margin_pct: Decimal | None


@dataclass(frozen=True)
class ScenarioRow:
    scenario_pct: Decimal
    avg_margin_pct: Decimal | None
    profitable_count: int


@dataclass(frozen=True)
class ReportSummary:
    counts: ReportCounts
    category_table: tuple[CategoryRow, ...]
    scenario_matrix: tuple[ScenarioRow, ...]


def build_summary(records: Iterable[ScanProductRecord], cost_config: CostConfig) -> ReportSummary:
    total = not_checked = no_offer = currency_mismatch = anomaly = computable = 0
    category_computable: dict[str, int] = defaultdict(int)
    category_excluded: dict[str, int] = defaultdict(int)
    category_margin_sum: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    scenario_margin_sum = [Decimal("0") for _ in SCENARIO_ADJUSTMENTS]
    scenario_profitable = [0 for _ in SCENARIO_ADJUSTMENTS]

    for record in records:
        total += 1
        evaluation = evaluate_record(record, cost_config)
        category = record.product.category

        if not evaluation.computable:
            category_excluded[category] += 1
            if evaluation.exclusion_reason == ExclusionReason.NOT_CHECKED:
                not_checked += 1
            elif evaluation.exclusion_reason == ExclusionReason.NO_OFFER:
                no_offer += 1
            elif evaluation.exclusion_reason == ExclusionReason.CURRENCY_MISMATCH:
                currency_mismatch += 1
            elif evaluation.exclusion_reason == ExclusionReason.ANOMALY:
                anomaly += 1
            continue

        computable += 1
        category_computable[category] += 1
        category_margin_sum[category] += evaluation.margin_matrix[_REFERENCE_SCENARIO_INDEX].margin_pct
        for i, result in enumerate(evaluation.margin_matrix):
            scenario_margin_sum[i] += result.margin_pct
            if result.margin > 0:
                scenario_profitable[i] += 1

    all_categories = sorted(set(category_computable) | set(category_excluded))
    category_table = tuple(
        CategoryRow(
            category=category,
            computable_count=category_computable.get(category, 0),
            excluded_count=category_excluded.get(category, 0),
            avg_margin_pct=(
                category_margin_sum[category] / category_computable[category]
                if category_computable.get(category)
                else None
            ),
        )
        for category in all_categories
    )

    scenario_matrix = tuple(
        ScenarioRow(
            scenario_pct=scenario_pct,
            avg_margin_pct=(scenario_margin_sum[i] / computable if computable else None),
            profitable_count=scenario_profitable[i],
        )
        for i, scenario_pct in enumerate(SCENARIO_ADJUSTMENTS)
    )

    return ReportSummary(
        counts=ReportCounts(
            total=total, computable=computable, not_checked=not_checked,
            no_offer=no_offer, currency_mismatch=currency_mismatch, anomaly=anomaly,
        ),
        category_table=category_table,
        scenario_matrix=scenario_matrix,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/reports/test_aggregate.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/reports/aggregate.py backend/tests/reports/test_aggregate.py
git commit -m "Add build_summary: verdict, global scenario matrix, per-category breakdown"
```

---

## Task 4: `list_product_rows` — filtered, sorted, paginated product drill-down

**Files:**
- Create: `backend/app/reports/products.py`
- Test: `backend/tests/reports/test_products.py`

**Interfaces:**
- Consumes: `ProductEvaluation`, `evaluate_record` from Task 1's `app.reports.evaluate`;
  `CostConfig`, `SCENARIO_ADJUSTMENTS` from `app.pricing.margin`; `ScanProductRecord` from
  `app.scans.models`.
- Produces: `VALID_SORTS = ("category", "margin_asc", "margin_desc", "name")`,
  `VALID_STATUSES = ("computable", "not_checked", "no_offer", "currency_mismatch", "anomaly")`,
  `ProductPage` (frozen dataclass: `rows: tuple[ProductEvaluation, ...]`, `total: int`,
  `page: int`, `page_size: int`),
  `list_product_rows(records, cost_config, *, category=None, status=None, sort="category",
  page=1, page_size=50) -> ProductPage`. Used by Task 5's `GET /scans/{id}/report/products`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/reports/test_products.py
from decimal import Decimal

from app.models.product import Product
from app.pricing.margin import CostConfig
from app.providers.base import OfferResult
from app.reports.products import list_product_rows
from app.scans.models import ProductStatus, ScanProductRecord

COST_CONFIG = CostConfig(
    commission_pct=Decimal("0.10"),
    shipping_cost=Decimal("15.00"),
    vat_pct=Decimal("0.23"),
    returns_pct=Decimal("0.02"),
)


def _make_product(**overrides) -> Product:
    defaults = dict(
        tenant_id="t1", source="csv", external_id="1", variant_id=None,
        name="B Product", ean="5901234123457",
        wholesale_price=Decimal("40.00"), currency="PLN", category="Elektronika",
    )
    defaults.update(overrides)
    return Product(**defaults)


def _make_offer(**overrides) -> OfferResult:
    defaults = dict(
        price=Decimal("100.00"), currency="PLN", seller="Shop",
        source_url="https://example.com/x", delivery_days=2,
        confidence=0.9, citations=(), raw_response="{}",
    )
    defaults.update(overrides)
    return OfferResult(**defaults)


def _make_record(record_id, *, status=ProductStatus.DONE, offer=None, **product_overrides) -> ScanProductRecord:
    return ScanProductRecord(
        id=record_id, scan_id="scan-1", product=_make_product(external_id=str(record_id), **product_overrides),
        status=status, was_stale=False, offer=offer,
    )


def test_paginates_results():
    records = [_make_record(i, offer=_make_offer(), name=f"Product {i}") for i in range(1, 6)]

    page1 = list_product_rows(records, COST_CONFIG, page=1, page_size=2)
    page2 = list_product_rows(records, COST_CONFIG, page=2, page_size=2)
    page3 = list_product_rows(records, COST_CONFIG, page=3, page_size=2)

    assert page1.total == 5
    assert len(page1.rows) == 2
    assert len(page2.rows) == 2
    assert len(page3.rows) == 1


def test_filters_by_category():
    records = [
        _make_record(1, offer=_make_offer(), category="Elektronika"),
        _make_record(2, offer=_make_offer(), category="Dom"),
    ]

    page = list_product_rows(records, COST_CONFIG, category="Dom")

    assert page.total == 1
    assert page.rows[0].record.product.category == "Dom"


def test_filters_by_status_computable():
    records = [
        _make_record(1, offer=_make_offer()),
        _make_record(2, status=ProductStatus.DONE, offer=None),
    ]

    page = list_product_rows(records, COST_CONFIG, status="computable")

    assert page.total == 1
    assert page.rows[0].computable is True


def test_filters_by_status_no_offer():
    records = [
        _make_record(1, offer=_make_offer()),
        _make_record(2, status=ProductStatus.DONE, offer=None),
    ]

    page = list_product_rows(records, COST_CONFIG, status="no_offer")

    assert page.total == 1
    assert page.rows[0].exclusion_reason.value == "no_offer"


def test_sorts_by_name():
    records = [
        _make_record(1, offer=_make_offer(), name="Zebra"),
        _make_record(2, offer=_make_offer(), name="Apple"),
    ]

    page = list_product_rows(records, COST_CONFIG, sort="name")

    assert [row.record.product.name for row in page.rows] == ["Apple", "Zebra"]


def test_sorts_by_margin_desc_and_puts_non_computable_rows_last():
    records = [
        _make_record(1, offer=_make_offer(price=Decimal("100.00")), wholesale_price=Decimal("60.00")),  # lower margin
        _make_record(2, offer=_make_offer(price=Decimal("100.00")), wholesale_price=Decimal("40.00")),  # higher margin
        _make_record(3, status=ProductStatus.DONE, offer=None),  # non-computable
    ]

    page = list_product_rows(records, COST_CONFIG, sort="margin_desc")

    assert [row.record.product.external_id for row in page.rows] == ["2", "1", "3"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/reports/test_products.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.reports.products'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/reports/products.py
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from app.pricing.margin import CostConfig, SCENARIO_ADJUSTMENTS
from app.reports.evaluate import ProductEvaluation, evaluate_record
from app.scans.models import ScanProductRecord

_REFERENCE_SCENARIO_INDEX = SCENARIO_ADJUSTMENTS.index(Decimal("0.00"))

VALID_SORTS = ("category", "margin_asc", "margin_desc", "name")
VALID_STATUSES = ("computable", "not_checked", "no_offer", "currency_mismatch", "anomaly")


@dataclass(frozen=True)
class ProductPage:
    rows: tuple[ProductEvaluation, ...]
    total: int
    page: int
    page_size: int


def _status_matches(evaluation: ProductEvaluation, status: str) -> bool:
    if status == "computable":
        return evaluation.computable
    return (
        not evaluation.computable
        and evaluation.exclusion_reason is not None
        and evaluation.exclusion_reason.value == status
    )


def _reference_margin_pct(evaluation: ProductEvaluation) -> Decimal | None:
    if not evaluation.computable or evaluation.margin_matrix is None:
        return None
    return evaluation.margin_matrix[_REFERENCE_SCENARIO_INDEX].margin_pct


def _sort_key(sort: str):
    if sort == "name":
        return lambda e: e.record.product.name
    if sort == "margin_asc":
        margin = _reference_margin_pct
        return lambda e: (margin(e) is None, margin(e) or Decimal("0"))
    if sort == "margin_desc":
        margin = _reference_margin_pct
        return lambda e: (margin(e) is None, -(margin(e) or Decimal("0")))
    return lambda e: (e.record.product.category, e.record.product.name)


def list_product_rows(
    records: Iterable[ScanProductRecord],
    cost_config: CostConfig,
    *,
    category: str | None = None,
    status: str | None = None,
    sort: str = "category",
    page: int = 1,
    page_size: int = 50,
) -> ProductPage:
    evaluations = [evaluate_record(record, cost_config) for record in records]
    if category is not None:
        evaluations = [e for e in evaluations if e.record.product.category == category]
    if status is not None:
        evaluations = [e for e in evaluations if _status_matches(e, status)]
    evaluations.sort(key=_sort_key(sort))

    total = len(evaluations)
    start = (page - 1) * page_size
    page_rows = tuple(evaluations[start : start + page_size])
    return ProductPage(rows=page_rows, total=total, page=page, page_size=page_size)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/reports/test_products.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/reports/products.py backend/tests/reports/test_products.py
git commit -m "Add list_product_rows: filtered, sorted, paginated product drill-down"
```

---

## Task 5: Report API endpoints

**Files:**
- Create: `backend/app/reports/api.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/reports/test_api.py`

**Interfaces:**
- Consumes: `get_store` from `app.scans.api` (existing shared-singleton dependency, reused
  rather than duplicated); `ScanStore` from `app.scans.store`; `CostConfig` from
  `app.pricing.margin`; `build_summary` from Task 3's `app.reports.aggregate`;
  `list_product_rows`, `VALID_SORTS`, `VALID_STATUSES` from Task 4's `app.reports.products`.
- Produces: `router: APIRouter` mounted in `main.py`, exposing `GET /scans/{scan_id}/report/summary`
  and `GET /scans/{scan_id}/report/products`, both documented in the design spec's API section.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/reports/test_api.py
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.product import Product
from app.providers.base import OfferResult
from app.reports.api import router
from app.scans.api import get_store
from app.scans.estimate import estimate_cost
from app.scans.store import ScanStore

COST_PARAMS = {
    "commission_pct": "0.10", "shipping_cost": "15.00",
    "vat_pct": "0.23", "returns_pct": "0.02",
}


def _make_app(tmp_path):
    app = FastAPI()
    app.include_router(router)
    store = ScanStore(tmp_path / "app.sqlite3")
    app.dependency_overrides[get_store] = lambda: store
    return app, store


def _make_product(**overrides) -> Product:
    defaults = dict(
        tenant_id="t1", source="csv", external_id="1", variant_id=None,
        name="Test Product", ean="5901234123457",
        wholesale_price=Decimal("40.00"), currency="PLN", category="Elektronika",
    )
    defaults.update(overrides)
    return Product(**defaults)


def _seed_done_scan(store: ScanStore, *, offer_price=Decimal("100.00")) -> str:
    estimate = estimate_cost(cache_misses=1, stale_count=0, max_concurrency=5)
    scan_id = store.create_scan(
        scope_type="full", sample_per_category=None, market="PL", max_delivery_days=5,
        max_concurrency=5, staleness_threshold_days=14,
        products=[_make_product()], stale_eans=(), estimate=estimate,
        overlapping_count=0, stale_count=0,
    )
    record = store.list_pending(scan_id)[0]
    offer = OfferResult(
        price=offer_price, currency="PLN", seller="Shop",
        source_url="https://example.com/x", delivery_days=2,
        confidence=0.9, citations=(), raw_response="{}",
    )
    store.mark_done(record.id, offer)
    store.finalize_scan(scan_id)
    return scan_id


def test_report_summary_returns_computed_aggregates(tmp_path):
    app, store = _make_app(tmp_path)
    client = TestClient(app)
    scan_id = _seed_done_scan(store)

    response = client.get(f"/scans/{scan_id}/report/summary", params=COST_PARAMS)

    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["total"] == 1
    assert body["counts"]["computable"] == 1
    assert len(body["scenario_matrix"]) == 4
    assert body["category_table"][0]["category"] == "Elektronika"
    store.close()


def test_report_summary_404_for_unknown_scan(tmp_path):
    app, store = _make_app(tmp_path)
    client = TestClient(app)

    response = client.get("/scans/does-not-exist/report/summary", params=COST_PARAMS)

    assert response.status_code == 404
    store.close()


def test_report_summary_400_when_scan_not_terminal(tmp_path):
    app, store = _make_app(tmp_path)
    client = TestClient(app)
    estimate = estimate_cost(cache_misses=1, stale_count=0, max_concurrency=5)
    scan_id = store.create_scan(
        scope_type="full", sample_per_category=None, market="PL", max_delivery_days=5,
        max_concurrency=5, staleness_threshold_days=14,
        products=[_make_product()], stale_eans=(), estimate=estimate,
        overlapping_count=0, stale_count=0,
    )

    response = client.get(f"/scans/{scan_id}/report/summary", params=COST_PARAMS)

    assert response.status_code == 400
    store.close()


def test_report_summary_400_for_negative_cost_value(tmp_path):
    app, store = _make_app(tmp_path)
    client = TestClient(app)
    scan_id = _seed_done_scan(store)

    response = client.get(
        f"/scans/{scan_id}/report/summary",
        params={**COST_PARAMS, "shipping_cost": "-5"},
    )

    assert response.status_code == 400
    store.close()


def test_report_products_returns_paginated_rows_with_offer_and_margin_matrix(tmp_path):
    app, store = _make_app(tmp_path)
    client = TestClient(app)
    scan_id = _seed_done_scan(store)

    response = client.get(
        f"/scans/{scan_id}/report/products",
        params={**COST_PARAMS, "page": 1, "page_size": 10},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    row = body["rows"][0]
    assert row["computable"] is True
    assert len(row["margin_matrix"]) == 4
    assert row["offer"]["seller"] == "Shop"
    assert isinstance(row["id"], int)
    store.close()


def test_report_products_400_for_invalid_sort(tmp_path):
    app, store = _make_app(tmp_path)
    client = TestClient(app)
    scan_id = _seed_done_scan(store)

    response = client.get(
        f"/scans/{scan_id}/report/products",
        params={**COST_PARAMS, "sort": "bogus"},
    )

    assert response.status_code == 400
    store.close()


def test_report_products_filters_by_status(tmp_path):
    app, store = _make_app(tmp_path)
    client = TestClient(app)
    scan_id = _seed_done_scan(store)

    response = client.get(
        f"/scans/{scan_id}/report/products",
        params={**COST_PARAMS, "status": "no_offer"},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 0
    store.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/reports/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.reports.api'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/reports/api.py
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query

from app.pricing.margin import CostConfig, MarginResult
from app.reports.aggregate import ReportSummary, build_summary
from app.reports.evaluate import ProductEvaluation
from app.reports.products import VALID_SORTS, VALID_STATUSES, ProductPage, list_product_rows
from app.scans.api import get_store
from app.scans.store import ScanStore

router = APIRouter()

REPORTABLE_STATUSES = ("done", "failed")


def _parse_decimal(name: str, value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise HTTPException(
            status_code=400, detail=f"{name} must be a valid decimal, got {value!r}"
        )
    if not parsed.is_finite() or parsed < 0:
        raise HTTPException(
            status_code=400, detail=f"{name} must be a non-negative number, got {value!r}"
        )
    return parsed


def _cost_config_from_query(
    commission_pct: str, shipping_cost: str, vat_pct: str, returns_pct: str
) -> CostConfig:
    return CostConfig(
        commission_pct=_parse_decimal("commission_pct", commission_pct),
        shipping_cost=_parse_decimal("shipping_cost", shipping_cost),
        vat_pct=_parse_decimal("vat_pct", vat_pct),
        returns_pct=_parse_decimal("returns_pct", returns_pct),
    )


def _require_reportable_scan(store: ScanStore, scan_id: str):
    scan = store.get_scan(scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="scan not found")
    if scan.status.value not in REPORTABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"report is only available once a scan is done or failed, got {scan.status.value!r}",
        )
    return scan


def _margin_result_to_dict(result: MarginResult) -> dict:
    return {
        "scenario_pct": str(result.scenario_pct),
        "sale_price": str(result.sale_price),
        "net_revenue": str(result.net_revenue),
        "total_costs": str(result.total_costs),
        "margin": str(result.margin),
        "margin_pct": str(result.margin_pct),
    }


def _summary_to_dict(summary: ReportSummary) -> dict:
    return {
        "counts": {
            "total": summary.counts.total,
            "computable": summary.counts.computable,
            "not_checked": summary.counts.not_checked,
            "no_offer": summary.counts.no_offer,
            "currency_mismatch": summary.counts.currency_mismatch,
            "anomaly": summary.counts.anomaly,
        },
        "category_table": [
            {
                "category": row.category,
                "computable_count": row.computable_count,
                "excluded_count": row.excluded_count,
                "avg_margin_pct": str(row.avg_margin_pct) if row.avg_margin_pct is not None else None,
            }
            for row in summary.category_table
        ],
        "scenario_matrix": [
            {
                "scenario_pct": str(row.scenario_pct),
                "avg_margin_pct": str(row.avg_margin_pct) if row.avg_margin_pct is not None else None,
                "profitable_count": row.profitable_count,
            }
            for row in summary.scenario_matrix
        ],
    }


def _evaluation_to_dict(evaluation: ProductEvaluation) -> dict:
    record = evaluation.record
    offer = record.offer
    return {
        "id": record.id,
        "external_id": record.product.external_id,
        "name": record.product.name,
        "category": record.product.category,
        "ean": record.product.ean,
        "wholesale_price": str(record.product.wholesale_price),
        "currency": record.product.currency,
        "computable": evaluation.computable,
        "exclusion_reason": evaluation.exclusion_reason.value if evaluation.exclusion_reason else None,
        "anomaly_flag": evaluation.anomaly_flag.value if evaluation.anomaly_flag else None,
        "offer": (
            {
                "price": str(offer.price),
                "currency": offer.currency,
                "seller": offer.seller,
                "source_url": offer.source_url,
                "delivery_days": offer.delivery_days,
                "confidence": offer.confidence,
                "citations": list(offer.citations),
            }
            if offer is not None
            else None
        ),
        "margin_matrix": (
            [_margin_result_to_dict(r) for r in evaluation.margin_matrix]
            if evaluation.margin_matrix is not None
            else None
        ),
    }


def _product_page_to_dict(page: ProductPage) -> dict:
    return {
        "total": page.total,
        "page": page.page,
        "page_size": page.page_size,
        "rows": [_evaluation_to_dict(e) for e in page.rows],
    }


@router.get("/scans/{scan_id}/report/summary")
async def get_report_summary(
    scan_id: str,
    commission_pct: str = Query(...),
    shipping_cost: str = Query(...),
    vat_pct: str = Query(...),
    returns_pct: str = Query(...),
    store: ScanStore = Depends(get_store),
):
    _require_reportable_scan(store, scan_id)
    cost_config = _cost_config_from_query(commission_pct, shipping_cost, vat_pct, returns_pct)
    records = store.list_all(scan_id)
    summary = build_summary(records, cost_config)
    return _summary_to_dict(summary)


@router.get("/scans/{scan_id}/report/products")
async def get_report_products(
    scan_id: str,
    commission_pct: str = Query(...),
    shipping_cost: str = Query(...),
    vat_pct: str = Query(...),
    returns_pct: str = Query(...),
    category: str | None = Query(None),
    status: str | None = Query(None),
    sort: str = Query("category"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    store: ScanStore = Depends(get_store),
):
    _require_reportable_scan(store, scan_id)
    if sort not in VALID_SORTS:
        raise HTTPException(status_code=400, detail=f"sort must be one of {VALID_SORTS!r}, got {sort!r}")
    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400, detail=f"status must be one of {VALID_STATUSES!r}, got {status!r}"
        )
    cost_config = _cost_config_from_query(commission_pct, shipping_cost, vat_pct, returns_pct)
    records = store.list_all(scan_id)
    result = list_product_rows(
        records, cost_config, category=category, status=status, sort=sort,
        page=page, page_size=page_size,
    )
    return _product_page_to_dict(result)
```

Update `backend/app/main.py`:

```python
# backend/app/main.py
from fastapi import FastAPI

from app.reports.api import router as reports_router
from app.scans.api import router as scans_router

app = FastAPI(title="IS_IT_WORTH_IT")
app.include_router(scans_router)
app.include_router(reports_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/reports/test_api.py tests/test_main.py -v`
Expected: PASS (7 + 1 tests)

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && python -m pytest`
Expected: all tests pass (previous count plus this plan's new tests; 2 pre-existing skips for
opt-in live-Perplexity tests are expected and fine).

- [ ] **Step 6: Commit**

```bash
git add backend/app/reports/api.py backend/app/main.py backend/tests/reports/test_api.py
git commit -m "Add GET /scans/{id}/report/summary and /report/products endpoints"
```

---

## Task 6: Frontend API types and client functions for the report

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/client.test.ts`

**Interfaces:**
- Produces: types `CostConfigInput`, `ExclusionReason`, `ReportCounts`, `CategoryRow`,
  `ScenarioRow`, `ReportSummary`, `MarginResult`, `ProductOffer`, `ProductRow`, `ProductPage`
  (all mirroring Task 5's JSON exactly — field names identical, `Decimal`s as `string`); functions
  `getReportSummary(scanId: string, costConfig: CostConfigInput): Promise<ReportSummary>` and
  `getReportProducts(scanId: string, costConfig: CostConfigInput, params?:
  ReportProductsParams): Promise<ProductPage>` where `ReportProductsParams = { category?: string;
  status?: string; sort?: string; page?: number; pageSize?: number }`. Both throw `ApiError` on a
  non-2xx response, same as every other `client.ts` function. Used by Tasks 7-8's `ReportStep`.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/api/client.test.ts` (it already imports `describe`/`expect`/`it`/`vi`/
`beforeEach`/`afterEach` and defines `jsonResponse` at module scope — reuse it):

```ts
describe('getReportSummary', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends cost config as query params and returns the parsed summary', async () => {
    const summary = {
      counts: { total: 1, computable: 1, not_checked: 0, no_offer: 0, currency_mismatch: 0, anomaly: 0 },
      category_table: [],
      scenario_matrix: [],
    }
    vi.mocked(fetch).mockResolvedValue(jsonResponse(summary))

    const result = await getReportSummary('scan-1', {
      commissionPct: '0.10', shippingCost: '15.00', vatPct: '0.23', returnsPct: '0.02',
    })

    expect(result).toEqual(summary)
    const [url] = vi.mocked(fetch).mock.calls[0]
    expect(url).toContain('/scans/scan-1/report/summary?')
    expect(url).toContain('commission_pct=0.10')
    expect(url).toContain('shipping_cost=15.00')
    expect(url).toContain('vat_pct=0.23')
    expect(url).toContain('returns_pct=0.02')
  })

  it('throws ApiError on a non-2xx response', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: 'bad request' }, 400))

    await expect(
      getReportSummary('scan-1', {
        commissionPct: '0.10', shippingCost: '15.00', vatPct: '0.23', returnsPct: '0.02',
      }),
    ).rejects.toMatchObject({ status: 400 })
  })
})

describe('getReportProducts', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends pagination, filter, and sort params', async () => {
    const page = { total: 0, page: 2, page_size: 10, rows: [] }
    vi.mocked(fetch).mockResolvedValue(jsonResponse(page))

    const result = await getReportProducts(
      'scan-1',
      { commissionPct: '0.10', shippingCost: '15.00', vatPct: '0.23', returnsPct: '0.02' },
      { category: 'Elektronika', status: 'computable', sort: 'margin_desc', page: 2, pageSize: 10 },
    )

    expect(result).toEqual(page)
    const [url] = vi.mocked(fetch).mock.calls[0]
    expect(url).toContain('/scans/scan-1/report/products?')
    expect(url).toContain('category=Elektronika')
    expect(url).toContain('status=computable')
    expect(url).toContain('sort=margin_desc')
    expect(url).toContain('page=2')
    expect(url).toContain('page_size=10')
  })

  it('defaults page to 1 and page_size to 50 when not given', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ total: 0, page: 1, page_size: 50, rows: [] }))

    await getReportProducts('scan-1', {
      commissionPct: '0.10', shippingCost: '15.00', vatPct: '0.23', returnsPct: '0.02',
    })

    const [url] = vi.mocked(fetch).mock.calls[0]
    expect(url).toContain('page=1')
    expect(url).toContain('page_size=50')
  })
})
```

Add the two new imports to the top of `client.test.ts`, alongside the existing ones:

```ts
import { getReportProducts, getReportSummary } from './client'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `getReportSummary`/`getReportProducts` are not exported from `./client`

- [ ] **Step 3: Write minimal implementation**

Append to `frontend/src/api/types.ts`:

```ts
export interface CostConfigInput {
  commissionPct: string
  shippingCost: string
  vatPct: string
  returnsPct: string
}

export type ExclusionReason = 'not_checked' | 'no_offer' | 'currency_mismatch' | 'anomaly'

export interface ReportCounts {
  total: number
  computable: number
  not_checked: number
  no_offer: number
  currency_mismatch: number
  anomaly: number
}

export interface CategoryRow {
  category: string
  computable_count: number
  excluded_count: number
  avg_margin_pct: string | null
}

export interface ScenarioRow {
  scenario_pct: string
  avg_margin_pct: string | null
  profitable_count: number
}

export interface ReportSummary {
  counts: ReportCounts
  category_table: CategoryRow[]
  scenario_matrix: ScenarioRow[]
}

export interface MarginResult {
  scenario_pct: string
  sale_price: string
  net_revenue: string
  total_costs: string
  margin: string
  margin_pct: string
}

export interface ProductOffer {
  price: string
  currency: string
  seller: string
  source_url: string
  delivery_days: number
  confidence: number
  citations: string[]
}

export interface ProductRow {
  id: number
  external_id: string
  name: string
  category: string
  ean: string | null
  wholesale_price: string
  currency: string
  computable: boolean
  exclusion_reason: ExclusionReason | null
  anomaly_flag: string | null
  offer: ProductOffer | null
  margin_matrix: MarginResult[] | null
}

export interface ProductPage {
  total: number
  page: number
  page_size: number
  rows: ProductRow[]
}
```

Append to `frontend/src/api/client.ts`:

```ts
import type {
  CostConfigInput,
  ProductPage,
  ReportSummary,
} from './types'

function costConfigParams(costConfig: CostConfigInput): Record<string, string> {
  return {
    commission_pct: costConfig.commissionPct,
    shipping_cost: costConfig.shippingCost,
    vat_pct: costConfig.vatPct,
    returns_pct: costConfig.returnsPct,
  }
}

export async function getReportSummary(
  scanId: string,
  costConfig: CostConfigInput,
): Promise<ReportSummary> {
  const params = new URLSearchParams(costConfigParams(costConfig))
  const response = await fetch(`/scans/${scanId}/report/summary?${params}`)
  if (!response.ok) {
    throw new ApiError(await errorDetail(response), response.status)
  }
  return response.json()
}

export interface ReportProductsParams {
  category?: string
  status?: string
  sort?: string
  page?: number
  pageSize?: number
}

export async function getReportProducts(
  scanId: string,
  costConfig: CostConfigInput,
  params: ReportProductsParams = {},
): Promise<ProductPage> {
  const query = new URLSearchParams(costConfigParams(costConfig))
  if (params.category) query.set('category', params.category)
  if (params.status) query.set('status', params.status)
  if (params.sort) query.set('sort', params.sort)
  query.set('page', String(params.page ?? 1))
  query.set('page_size', String(params.pageSize ?? 50))

  const response = await fetch(`/scans/${scanId}/report/products?${query}`)
  if (!response.ok) {
    throw new ApiError(await errorDetail(response), response.status)
  }
  return response.json()
}
```

(`client.ts`'s existing `import type { CreateScanResult, Scan, ScopeConfig } from './types'` stays
as-is; the block above is a second, additional `import type` line, since TypeScript allows and this
codebase's style favors grouping each addition with what it's for. `ApiError` and `errorDetail` are
already defined earlier in the same file — no need to redefine them.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (all `client.test.ts` tests, including the 4 new ones)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/api/client.test.ts
git commit -m "Add API types and client functions for the report endpoints"
```

---

## Task 7: `ReportStep` — verdict, cost-config card, exclusion chips, scenario matrix, category table

**Files:**
- Create: `frontend/src/steps/ReportStep.tsx`
- Test: `frontend/src/steps/ReportStep.test.tsx`

**Interfaces:**
- Consumes: `getReportSummary` from Task 6's `../api/client`; `CostConfigInput`, `ReportSummary`
  from `../api/types`.
- Produces: `ReportStep({ scanId }: { scanId: string })`. On mount, loads the summary using a
  `localStorage`-backed default cost config and renders the verdict numeral, the cost-config card,
  exclusion-count chips, the scenario matrix, and the category table. Exports a module-scope
  `formatPct(value: string | null): string` helper, reused unmodified by Task 8. Used by Task 9's
  `App.tsx`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/steps/ReportStep.test.tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ReportStep } from './ReportStep'
import * as client from '../api/client'

const SUMMARY = {
  counts: { total: 10, computable: 8, not_checked: 0, no_offer: 1, currency_mismatch: 0, anomaly: 1 },
  category_table: [
    { category: 'Elektronika', computable_count: 8, excluded_count: 2, avg_margin_pct: '0.1200' },
  ],
  scenario_matrix: [
    { scenario_pct: '-0.10', avg_margin_pct: '0.0200', profitable_count: 5 },
    { scenario_pct: '-0.05', avg_margin_pct: '0.0700', profitable_count: 6 },
    { scenario_pct: '0.00', avg_margin_pct: '0.1200', profitable_count: 7 },
    { scenario_pct: '0.05', avg_margin_pct: '0.1700', profitable_count: 8 },
  ],
}

beforeEach(() => {
  localStorage.clear()
})
afterEach(() => {
  vi.restoreAllMocks()
})

describe('ReportStep', () => {
  it('loads the summary on mount using the default cost config and shows the verdict', async () => {
    const spy = vi.spyOn(client, 'getReportSummary').mockResolvedValue(SUMMARY)
    render(<ReportStep scanId="scan-1" />)

    expect(await screen.findByText('+12.0%')).toBeInTheDocument()
    expect(spy).toHaveBeenCalledWith('scan-1', {
      commissionPct: '0.15', shippingCost: '0.00', vatPct: '0.23', returnsPct: '0.05',
    })
  })

  it('shows the exclusion counts as chips, only for non-zero counts', async () => {
    vi.spyOn(client, 'getReportSummary').mockResolvedValue(SUMMARY)
    render(<ReportStep scanId="scan-1" />)

    expect(await screen.findByText('1 bez oferty')).toBeInTheDocument()
    expect(screen.getByText('1 oflagowanych')).toBeInTheDocument()
    expect(screen.queryByText(/innej waluty/)).not.toBeInTheDocument()
    expect(screen.queryByText(/nie sprawdzono/)).not.toBeInTheDocument()
  })

  it('shows the scenario matrix and category table', async () => {
    vi.spyOn(client, 'getReportSummary').mockResolvedValue(SUMMARY)
    render(<ReportStep scanId="scan-1" />)

    await screen.findByText('+12.0%')
    expect(screen.getByText('5 rentownych')).toBeInTheDocument()
    expect(screen.getByText('Elektronika')).toBeInTheDocument()
  })

  it('recalculates with edited cost config when Przelicz is clicked, and persists to localStorage', async () => {
    const spy = vi.spyOn(client, 'getReportSummary').mockResolvedValue(SUMMARY)
    render(<ReportStep scanId="scan-1" />)
    await screen.findByText('+12.0%')

    const commissionInput = screen.getByLabelText('Prowizja')
    await userEvent.clear(commissionInput)
    await userEvent.type(commissionInput, '0.20')
    await userEvent.click(screen.getByRole('button', { name: 'Przelicz' }))

    await waitFor(() =>
      expect(spy).toHaveBeenLastCalledWith('scan-1', {
        commissionPct: '0.20', shippingCost: '0.00', vatPct: '0.23', returnsPct: '0.05',
      }),
    )
    expect(JSON.parse(localStorage.getItem('isItWorthIt.costConfig')!)).toEqual({
      commissionPct: '0.20', shippingCost: '0.00', vatPct: '0.23', returnsPct: '0.05',
    })
  })

  it('loads persisted cost config from localStorage on mount', async () => {
    localStorage.setItem(
      'isItWorthIt.costConfig',
      JSON.stringify({ commissionPct: '0.25', shippingCost: '10.00', vatPct: '0.23', returnsPct: '0.03' }),
    )
    const spy = vi.spyOn(client, 'getReportSummary').mockResolvedValue(SUMMARY)
    render(<ReportStep scanId="scan-1" />)

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('scan-1', {
        commissionPct: '0.25', shippingCost: '10.00', vatPct: '0.23', returnsPct: '0.03',
      }),
    )
  })

  it('shows an empty state when there are no computable products', async () => {
    vi.spyOn(client, 'getReportSummary').mockResolvedValue({
      counts: { total: 3, computable: 0, not_checked: 0, no_offer: 3, currency_mismatch: 0, anomaly: 0 },
      category_table: [],
      scenario_matrix: [
        { scenario_pct: '-0.10', avg_margin_pct: null, profitable_count: 0 },
        { scenario_pct: '-0.05', avg_margin_pct: null, profitable_count: 0 },
        { scenario_pct: '0.00', avg_margin_pct: null, profitable_count: 0 },
        { scenario_pct: '0.05', avg_margin_pct: null, profitable_count: 0 },
      ],
    })
    render(<ReportStep scanId="scan-1" />)

    expect(await screen.findByText('Brak danych do policzenia')).toBeInTheDocument()
  })

  it('shows the API error message when the summary request fails', async () => {
    const { ApiError } = await import('../api/types')
    vi.spyOn(client, 'getReportSummary').mockRejectedValue(new ApiError('scan not found', 404))
    render(<ReportStep scanId="scan-1" />)

    expect(await screen.findByText('scan not found')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL with `Cannot find module './ReportStep'`

- [ ] **Step 3: Write minimal implementation**

```tsx
// frontend/src/steps/ReportStep.tsx
import { useEffect, useState } from 'react'
import { getReportSummary } from '../api/client'
import { ApiError } from '../api/types'
import type { CostConfigInput, ReportSummary } from '../api/types'

const STORAGE_KEY = 'isItWorthIt.costConfig'

const DEFAULT_COST_CONFIG: CostConfigInput = {
  commissionPct: '0.15',
  shippingCost: '0.00',
  vatPct: '0.23',
  returnsPct: '0.05',
}

function loadStoredCostConfig(): CostConfigInput {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_COST_CONFIG
    const parsed = JSON.parse(raw)
    return {
      commissionPct: String(parsed.commissionPct ?? DEFAULT_COST_CONFIG.commissionPct),
      shippingCost: String(parsed.shippingCost ?? DEFAULT_COST_CONFIG.shippingCost),
      vatPct: String(parsed.vatPct ?? DEFAULT_COST_CONFIG.vatPct),
      returnsPct: String(parsed.returnsPct ?? DEFAULT_COST_CONFIG.returnsPct),
    }
  } catch {
    return DEFAULT_COST_CONFIG
  }
}

export function formatPct(value: string | null): string {
  if (value === null) return '—'
  return `${(Number(value) * 100).toFixed(1)}%`
}

interface ReportStepProps {
  scanId: string
}

export function ReportStep({ scanId }: ReportStepProps) {
  const [costConfig, setCostConfig] = useState<CostConfigInput>(loadStoredCostConfig)
  const [summary, setSummary] = useState<ReportSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  async function recalculate() {
    setError(null)
    setIsLoading(true)
    try {
      const result = await getReportSummary(scanId, costConfig)
      setSummary(result)
      localStorage.setItem(STORAGE_KEY, JSON.stringify(costConfig))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Nie udało się policzyć raportu')
    } finally {
      setIsLoading(false)
    }
  }

  // Runs once per scan (not per keystroke in the cost-config card below —
  // that's deliberate, see recalculate() and the "Przelicz" button).
  useEffect(() => {
    recalculate()
  }, [scanId])

  const referenceScenario = summary?.scenario_matrix.find((row) => row.scenario_pct === '0.00') ?? null
  const verdictValue = referenceScenario?.avg_margin_pct ?? null
  const verdictPositive = verdictValue !== null && Number(verdictValue) > 0

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-16 p-8">
      <section className="flex flex-col items-center gap-2 text-center">
        {verdictValue === null ? (
          <p className="text-2xl font-medium text-slate-400">Brak danych do policzenia</p>
        ) : (
          <>
            <p
              className={`text-6xl font-semibold tabular-nums ${
                verdictPositive ? 'text-emerald-400' : 'text-rose-400'
              }`}
            >
              {verdictPositive ? '+' : ''}
              {formatPct(verdictValue)}
            </p>
            <p className="text-sm text-slate-400">
              {referenceScenario?.profitable_count ?? 0} / {summary?.counts.computable ?? 0}{' '}
              produktów rentownych przy cenie rynkowej
            </p>
          </>
        )}
      </section>

      <section className="flex flex-col gap-4">
        <div className="divide-y divide-slate-800/60 rounded-2xl border border-slate-800 bg-slate-900/40">
          <label className="flex items-center justify-between gap-4 p-4 text-sm text-slate-300">
            Prowizja
            <input
              type="number"
              step="0.01"
              min={0}
              value={costConfig.commissionPct}
              onChange={(e) => setCostConfig({ ...costConfig, commissionPct: e.target.value })}
              className="w-28 rounded-lg border border-slate-700 bg-slate-950 p-2 text-right text-slate-100"
            />
          </label>
          <label className="flex items-center justify-between gap-4 p-4 text-sm text-slate-300">
            Wysyłka
            <input
              type="number"
              step="0.01"
              min={0}
              value={costConfig.shippingCost}
              onChange={(e) => setCostConfig({ ...costConfig, shippingCost: e.target.value })}
              className="w-28 rounded-lg border border-slate-700 bg-slate-950 p-2 text-right text-slate-100"
            />
          </label>
          <label className="flex items-center justify-between gap-4 p-4 text-sm text-slate-300">
            VAT
            <input
              type="number"
              step="0.01"
              min={0}
              value={costConfig.vatPct}
              onChange={(e) => setCostConfig({ ...costConfig, vatPct: e.target.value })}
              className="w-28 rounded-lg border border-slate-700 bg-slate-950 p-2 text-right text-slate-100"
            />
          </label>
          <label className="flex items-center justify-between gap-4 p-4 text-sm text-slate-300">
            Zwroty
            <input
              type="number"
              step="0.01"
              min={0}
              value={costConfig.returnsPct}
              onChange={(e) => setCostConfig({ ...costConfig, returnsPct: e.target.value })}
              className="w-28 rounded-lg border border-slate-700 bg-slate-950 p-2 text-right text-slate-100"
            />
          </label>
        </div>
        <button
          type="button"
          onClick={recalculate}
          disabled={isLoading}
          className="self-start rounded-md bg-emerald-600 px-4 py-2 font-medium text-slate-950 disabled:bg-slate-700 disabled:text-slate-400"
        >
          Przelicz
        </button>
        {error && <p className="text-sm text-red-400">{error}</p>}
      </section>

      {summary && (
        <section className="flex flex-wrap gap-2">
          {summary.counts.no_offer > 0 && (
            <span className="rounded-full bg-slate-900 px-3 py-1 text-xs text-amber-400">
              {summary.counts.no_offer} bez oferty
            </span>
          )}
          {summary.counts.anomaly > 0 && (
            <span className="rounded-full bg-slate-900 px-3 py-1 text-xs text-amber-400">
              {summary.counts.anomaly} oflagowanych
            </span>
          )}
          {summary.counts.currency_mismatch > 0 && (
            <span className="rounded-full bg-slate-900 px-3 py-1 text-xs text-amber-400">
              {summary.counts.currency_mismatch} innej waluty
            </span>
          )}
          {summary.counts.not_checked > 0 && (
            <span className="rounded-full bg-slate-900 px-3 py-1 text-xs text-amber-400">
              {summary.counts.not_checked} nie sprawdzono
            </span>
          )}
        </section>
      )}

      {summary && (
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {summary.scenario_matrix.map((row) => {
            const positive = row.avg_margin_pct !== null && Number(row.avg_margin_pct) > 0
            return (
              <div key={row.scenario_pct} className="rounded-2xl border border-slate-800 p-6">
                <p className="text-xs uppercase tracking-wide text-slate-500">
                  {formatPct(row.scenario_pct)}
                </p>
                <p
                  className={`text-3xl font-semibold tabular-nums ${
                    row.avg_margin_pct === null
                      ? 'text-slate-500'
                      : positive
                        ? 'text-emerald-400'
                        : 'text-rose-400'
                  }`}
                >
                  {formatPct(row.avg_margin_pct)}
                </p>
                <p className="text-xs text-slate-500">{row.profitable_count} rentownych</p>
              </div>
            )
          })}
        </section>
      )}

      {summary && summary.category_table.length > 0 && (
        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-medium text-slate-400">Kategorie</h2>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800/60 text-left text-slate-500">
                <th className="py-2 font-normal">Kategoria</th>
                <th className="py-2 text-right font-normal">Policzone</th>
                <th className="py-2 text-right font-normal">Wykluczone</th>
                <th className="py-2 text-right font-normal">Śr. marża</th>
              </tr>
            </thead>
            <tbody>
              {summary.category_table.map((row) => (
                <tr key={row.category} className="border-b border-slate-800/60">
                  <td className="py-2 text-slate-200">{row.category}</td>
                  <td className="py-2 text-right tabular-nums text-slate-300">{row.computable_count}</td>
                  <td className="py-2 text-right tabular-nums text-slate-300">{row.excluded_count}</td>
                  <td className="py-2 text-right tabular-nums text-slate-300">
                    {formatPct(row.avg_margin_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/steps/ReportStep.tsx frontend/src/steps/ReportStep.test.tsx
git commit -m "Add ReportStep: verdict, cost-config card, exclusion chips, scenario matrix, category table"
```

---

## Task 8: `ReportStep` product drill-down

**Files:**
- Modify: `frontend/src/steps/ReportStep.tsx`
- Modify: `frontend/src/steps/ReportStep.test.tsx`

**Interfaces:**
- Consumes: `getReportProducts` from Task 6's `../api/client`; `ProductPage`, `ProductRow` from
  `../api/types`; Task 7's `formatPct`, `costConfig` state, `recalculate`.
- Produces: extends `ReportStep` with a filter/sort/paginated product table. Each row expands to
  show offer details (seller, clickable source URL, delivery days, confidence, anomaly flag) and
  the full 4-scenario margin matrix for that one product. `ReportStep`'s public interface
  (`{ scanId }`) is unchanged — this task only adds internal behavior. No later task depends on
  anything new here.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/steps/ReportStep.test.tsx`:

```tsx
const PRODUCT_PAGE = {
  total: 2,
  page: 1,
  page_size: 25,
  rows: [
    {
      id: 1, external_id: 'p1', name: 'Zebra Gadget', category: 'Elektronika', ean: '123',
      wholesale_price: '40.00', currency: 'PLN', computable: true,
      exclusion_reason: null, anomaly_flag: null,
      offer: {
        price: '100.00', currency: 'PLN', seller: 'Shop', source_url: 'https://example.com/x',
        delivery_days: 2, confidence: 0.9, citations: [],
      },
      margin_matrix: [
        { scenario_pct: '-0.10', sale_price: '90.00', net_revenue: '73.17', total_costs: '64.80', margin: '8.37', margin_pct: '0.0930' },
        { scenario_pct: '-0.05', sale_price: '95.00', net_revenue: '77.24', total_costs: '68.30', margin: '8.94', margin_pct: '0.0941' },
        { scenario_pct: '0.00', sale_price: '100.00', net_revenue: '81.30', total_costs: '54.00', margin: '27.30', margin_pct: '0.2730' },
        { scenario_pct: '0.05', sale_price: '105.00', net_revenue: '85.37', total_costs: '75.30', margin: '10.07', margin_pct: '0.0959' },
      ],
    },
    {
      id: 2, external_id: 'p2', name: 'Apple Widget', category: 'Elektronika', ean: null,
      wholesale_price: '30.00', currency: 'PLN', computable: false,
      exclusion_reason: 'no_offer', anomaly_flag: null,
      offer: null, margin_matrix: null,
    },
  ],
}

describe('ReportStep product drill-down', () => {
  it('loads and renders the product page after the summary loads', async () => {
    vi.spyOn(client, 'getReportSummary').mockResolvedValue(SUMMARY)
    const productsSpy = vi.spyOn(client, 'getReportProducts').mockResolvedValue(PRODUCT_PAGE)
    render(<ReportStep scanId="scan-1" />)

    await screen.findByText('Zebra Gadget')
    expect(screen.getByText('Apple Widget')).toBeInTheDocument()
    expect(productsSpy).toHaveBeenCalledWith(
      'scan-1',
      { commissionPct: '0.15', shippingCost: '0.00', vatPct: '0.23', returnsPct: '0.05' },
      { category: undefined, status: undefined, sort: 'category', page: 1, pageSize: 25 },
    )
  })

  it('expands a row to show offer details and the full margin matrix', async () => {
    vi.spyOn(client, 'getReportSummary').mockResolvedValue(SUMMARY)
    vi.spyOn(client, 'getReportProducts').mockResolvedValue(PRODUCT_PAGE)
    render(<ReportStep scanId="scan-1" />)
    await screen.findByText('Zebra Gadget')

    await userEvent.click(screen.getByText('Zebra Gadget'))

    expect(await screen.findByText('Shop')).toBeInTheDocument()
    expect(screen.getByText('https://example.com/x')).toBeInTheDocument()
  })

  it('reloads page 1 when the status filter changes', async () => {
    vi.spyOn(client, 'getReportSummary').mockResolvedValue(SUMMARY)
    const productsSpy = vi.spyOn(client, 'getReportProducts').mockResolvedValue(PRODUCT_PAGE)
    render(<ReportStep scanId="scan-1" />)
    await screen.findByText('Zebra Gadget')

    await userEvent.selectOptions(screen.getByLabelText('Status'), 'no_offer')

    await waitFor(() =>
      expect(productsSpy).toHaveBeenLastCalledWith(
        'scan-1',
        { commissionPct: '0.15', shippingCost: '0.00', vatPct: '0.23', returnsPct: '0.05' },
        { category: undefined, status: 'no_offer', sort: 'category', page: 1, pageSize: 25 },
      ),
    )
  })

  it('requests the next page when Następna is clicked', async () => {
    vi.spyOn(client, 'getReportSummary').mockResolvedValue(SUMMARY)
    const productsSpy = vi.spyOn(client, 'getReportProducts').mockResolvedValue({
      ...PRODUCT_PAGE, total: 30,
    })
    render(<ReportStep scanId="scan-1" />)
    await screen.findByText('Zebra Gadget')

    await userEvent.click(screen.getByRole('button', { name: 'Następna' }))

    await waitFor(() =>
      expect(productsSpy).toHaveBeenLastCalledWith(
        'scan-1',
        { commissionPct: '0.15', shippingCost: '0.00', vatPct: '0.23', returnsPct: '0.05' },
        { category: undefined, status: undefined, sort: 'category', page: 2, pageSize: 25 },
      ),
    )
  })
})
```

Add `ProductPage`-typed spy usage requires no new imports — `client` and `ReportStep` are already
imported at the top of the file from Task 7.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `getReportProducts` is never called by `ReportStep` yet, and none of "Zebra
Gadget" / "Status" / "Następna" exist in the rendered output.

- [ ] **Step 3: Write minimal implementation**

Add this import to the top of `frontend/src/steps/ReportStep.tsx`, alongside the existing ones:

```tsx
import { getReportProducts, getReportSummary } from '../api/client'
import type { CostConfigInput, ProductRow, ReportSummary, ProductPage } from '../api/types'
```

(This replaces the Task 7 import lines that only pulled in `getReportSummary` and
`CostConfigInput`/`ReportSummary` — the new lines are supersets, so just replace them.)

Add these constants and helpers near the top of the file, after `DEFAULT_COST_CONFIG`:

```tsx
const PAGE_SIZE = 25

const STATUS_LABELS: Record<string, string> = {
  computable: 'Policzone',
  not_checked: 'Nie sprawdzono',
  no_offer: 'Brak oferty',
  currency_mismatch: 'Inna waluta',
  anomaly: 'Oflagowane',
}

function statusLabel(row: ProductRow): string {
  return STATUS_LABELS[row.computable ? 'computable' : row.exclusion_reason ?? 'no_offer']
}

function marginAtZero(row: ProductRow): string | null {
  const match = row.margin_matrix?.find((m) => m.scenario_pct === '0.00')
  return match ? match.margin_pct : null
}

function ProductDetail({ row }: { row: ProductRow }) {
  return (
    <div className="flex flex-col gap-2 rounded-xl bg-slate-900/60 p-4 text-sm text-slate-300">
      {row.offer ? (
        <>
          <p>
            Sprzedawca: <span className="text-slate-100">{row.offer.seller}</span>
          </p>
          <p>
            Źródło:{' '}
            <a
              href={row.offer.source_url}
              target="_blank"
              rel="noreferrer"
              className="text-emerald-400 underline"
            >
              {row.offer.source_url}
            </a>
          </p>
          <p>Czas dostawy: {row.offer.delivery_days} dni</p>
          <p>Pewność: {(row.offer.confidence * 100).toFixed(0)}%</p>
        </>
      ) : (
        <p>Brak znalezionej oferty.</p>
      )}
      {row.anomaly_flag && <p className="text-amber-400">Flaga: {row.anomaly_flag}</p>}
      {row.margin_matrix && (
        <table className="mt-2 w-full text-xs">
          <thead>
            <tr className="text-left text-slate-500">
              <th className="font-normal">Scenariusz</th>
              <th className="text-right font-normal">Marża %</th>
              <th className="text-right font-normal">Cena sprzedaży</th>
            </tr>
          </thead>
          <tbody>
            {row.margin_matrix.map((m) => (
              <tr key={m.scenario_pct}>
                <td>{formatPct(m.scenario_pct)}</td>
                <td className="text-right tabular-nums">{formatPct(m.margin_pct)}</td>
                <td className="text-right tabular-nums">{m.sale_price}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function ProductRowCard({
  row, expanded, onToggle,
}: {
  row: ProductRow
  expanded: boolean
  onToggle: () => void
}) {
  const margin = marginAtZero(row)
  return (
    <div className="rounded-xl border border-slate-800/60">
      <button
        type="button"
        onClick={onToggle}
        className="grid w-full grid-cols-1 gap-1 p-4 text-left md:grid-cols-[1fr_140px_100px_140px] md:items-center md:gap-4"
      >
        <span className="text-sm font-medium text-slate-100">{row.name}</span>
        <span className="text-xs text-slate-400 md:text-sm">{row.category}</span>
        <span className="text-sm tabular-nums text-slate-300 md:text-right">{formatPct(margin)}</span>
        <span className="text-xs text-slate-400 md:text-sm">{statusLabel(row)}</span>
      </button>
      {expanded && (
        <div className="border-t border-slate-800/60 p-4">
          <ProductDetail row={row} />
        </div>
      )}
    </div>
  )
}
```

Inside the `ReportStep` component, add state (alongside the existing `costConfig`/`summary`/
`error`/`isLoading`):

```tsx
  const [category, setCategory] = useState('')
  const [status, setStatus] = useState('')
  const [sort, setSort] = useState('category')
  const [productPage, setProductPage] = useState<ProductPage | null>(null)
  const [productsError, setProductsError] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<number | null>(null)

  async function loadProducts(overrides: { category?: string; status?: string; sort?: string; page: number }) {
    setProductsError(null)
    const effectiveCategory = overrides.category ?? category
    const effectiveStatus = overrides.status ?? status
    const effectiveSort = overrides.sort ?? sort
    try {
      const result = await getReportProducts(scanId, costConfig, {
        category: effectiveCategory || undefined,
        status: effectiveStatus || undefined,
        sort: effectiveSort,
        page: overrides.page,
        pageSize: PAGE_SIZE,
      })
      setProductPage(result)
    } catch (err) {
      setProductsError(err instanceof ApiError ? err.message : 'Nie udało się wczytać produktów')
    }
  }

  function handleCategoryChange(value: string) {
    setCategory(value)
    loadProducts({ category: value, page: 1 })
  }

  function handleStatusChange(value: string) {
    setStatus(value)
    loadProducts({ status: value, page: 1 })
  }

  function handleSortChange(value: string) {
    setSort(value)
    loadProducts({ sort: value, page: 1 })
  }

  function handlePrevPage() {
    const current = productPage?.page ?? 1
    loadProducts({ page: Math.max(1, current - 1) })
  }

  function handleNextPage() {
    const current = productPage?.page ?? 1
    loadProducts({ page: current + 1 })
  }
```

Replace the existing `recalculate` function's body (Task 7's version) with this, which now also
loads page 1 of the product table on success:

```tsx
  async function recalculate() {
    setError(null)
    setIsLoading(true)
    try {
      const result = await getReportSummary(scanId, costConfig)
      setSummary(result)
      localStorage.setItem(STORAGE_KEY, JSON.stringify(costConfig))
      await loadProducts({ page: 1 })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Nie udało się policzyć raportu')
    } finally {
      setIsLoading(false)
    }
  }
```

Add this new section at the end of the returned JSX, right after the category-table `section`
block (still inside the outer `<div className="mx-auto flex max-w-3xl ...">`):

```tsx
      {productPage && (
        <section className="flex flex-col gap-4">
          <h2 className="text-sm font-medium text-slate-400">Produkty</h2>
          <div className="flex flex-wrap gap-3 text-sm">
            <label className="flex items-center gap-2 text-slate-300">
              Kategoria
              <select
                value={category}
                onChange={(e) => handleCategoryChange(e.target.value)}
                className="rounded-lg border border-slate-700 bg-slate-950 p-2 text-slate-100"
              >
                <option value="">Wszystkie</option>
                {Array.from(new Set(summary?.category_table.map((r) => r.category) ?? [])).map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2 text-slate-300">
              Status
              <select
                value={status}
                onChange={(e) => handleStatusChange(e.target.value)}
                className="rounded-lg border border-slate-700 bg-slate-950 p-2 text-slate-100"
              >
                <option value="">Wszystkie</option>
                <option value="computable">Policzone</option>
                <option value="no_offer">Bez oferty</option>
                <option value="anomaly">Oflagowane</option>
                <option value="currency_mismatch">Inna waluta</option>
                <option value="not_checked">Nie sprawdzono</option>
              </select>
            </label>
            <label className="flex items-center gap-2 text-slate-300">
              Sortowanie
              <select
                value={sort}
                onChange={(e) => handleSortChange(e.target.value)}
                className="rounded-lg border border-slate-700 bg-slate-950 p-2 text-slate-100"
              >
                <option value="category">Kategoria</option>
                <option value="name">Nazwa</option>
                <option value="margin_desc">Marża malejąco</option>
                <option value="margin_asc">Marża rosnąco</option>
              </select>
            </label>
          </div>

          {productsError && <p className="text-sm text-red-400">{productsError}</p>}

          <div className="flex flex-col gap-2">
            {productPage.rows.map((row) => (
              <ProductRowCard
                key={row.id}
                row={row}
                expanded={expandedId === row.id}
                onToggle={() => setExpandedId(expandedId === row.id ? null : row.id)}
              />
            ))}
          </div>

          <div className="flex items-center justify-between text-sm text-slate-400">
            <button
              type="button"
              onClick={handlePrevPage}
              disabled={productPage.page <= 1}
              className="rounded-md border border-slate-700 px-3 py-1.5 disabled:opacity-40"
            >
              Poprzednia
            </button>
            <span>
              Strona {productPage.page} z {Math.max(1, Math.ceil(productPage.total / productPage.page_size))}
            </span>
            <button
              type="button"
              onClick={handleNextPage}
              disabled={productPage.page * productPage.page_size >= productPage.total}
              className="rounded-md border border-slate-700 px-3 py-1.5 disabled:opacity-40"
            >
              Następna
            </button>
          </div>
        </section>
      )}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (11 tests in `ReportStep.test.tsx`)

- [ ] **Step 5: Run the linter**

Run: `cd frontend && npm run lint`
Expected: clean. Fix anything oxlint flags before committing.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/steps/ReportStep.tsx frontend/src/steps/ReportStep.test.tsx
git commit -m "Add product drill-down to ReportStep: filter, sort, paginate, expand for detail"
```

---

## Task 9: Wire `ReportStep` into the wizard

**Files:**
- Modify: `frontend/src/steps/ProgressStep.tsx`
- Modify: `frontend/src/steps/ProgressStep.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: `ReportStep` from Task 8's `./steps/ReportStep`.
- Produces: `ProgressStep` gains an `onDone: (scanId: string) => void` prop, called when the user
  clicks a new "Zobacz raport" button that appears once `scan.status` is `done` or `failed`.
  `App.tsx` gains a `'report'` `WizardStep` value, rendering `<ReportStep scanId={scanId} />`.

- [ ] **Step 1: Write the failing test**

Update every `render(<ProgressStep scanId="scan-1" />)` call already in
`frontend/src/steps/ProgressStep.test.tsx` to `render(<ProgressStep scanId="scan-1" onDone={vi.fn()} />)`
(there are 4 — one per existing `it` block). Then add a new test at the end of the `describe`
block:

```tsx
  it('calls onDone with the scan id when Zobacz raport is clicked, once the scan is done', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    const onDone = vi.fn()
    mockScanEvents({
      scan: {
        scan_id: 'scan-1', status: 'done', scope_type: 'full',
        total_products: 20, completed_products: 20,
        estimate: {
          queries_without_refresh: 20, queries_with_refresh: 20,
          cost_usd_without_refresh: '0.20', cost_usd_with_refresh: '0.20',
          seconds_without_refresh: 10, seconds_with_refresh: 10,
        },
        overlapping_count: 0, stale_count: 0,
      },
    })

    render(<ProgressStep scanId="scan-1" onDone={onDone} />)
    await userEvent.click(screen.getByRole('button', { name: 'Zobacz raport' }))

    expect(onDone).toHaveBeenCalledWith('scan-1')
  })
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — TypeScript error (`onDone` missing from props) and/or "Zobacz raport" button not
found.

- [ ] **Step 3: Write minimal implementation**

Replace `frontend/src/steps/ProgressStep.tsx` in full:

```tsx
// frontend/src/steps/ProgressStep.tsx
import { useScanEvents } from '../api/useScanEvents'

interface ProgressStepProps {
  scanId: string
  onDone: (scanId: string) => void
}

export function ProgressStep({ scanId, onDone }: ProgressStepProps) {
  const { scan, source, error } = useScanEvents(scanId)

  if (error) {
    return (
      <div className="mx-auto max-w-md p-8">
        <p className="text-sm text-red-400">{error}</p>
      </div>
    )
  }

  if (!scan) {
    return (
      <div className="mx-auto max-w-md p-8">
        <p className="text-sm text-slate-400">Łączenie ze skanem…</p>
      </div>
    )
  }

  const percent = scan.total_products > 0
    ? Math.round((scan.completed_products / scan.total_products) * 100)
    : 0
  const isTerminal = scan.status === 'done' || scan.status === 'failed'

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4 p-8">
      <h1 className="text-xl font-semibold text-slate-100">Przebieg skanu</h1>
      <div className="h-3 w-full rounded-full bg-slate-800">
        <div
          className="h-3 rounded-full bg-emerald-500 transition-all"
          style={{ width: `${percent}%` }}
        />
      </div>
      <p className="text-sm text-slate-300">
        {scan.completed_products} / {scan.total_products}
      </p>
      {source === 'polling' && (
        <p className="text-xs text-slate-500">
          Połączenie na żywo zerwane — aktualizacja co kilka sekund.
        </p>
      )}
      {isTerminal && (
        <>
          <p
            className={`text-sm font-medium ${
              scan.status === 'failed' ? 'text-red-400' : 'text-emerald-400'
            }`}
          >
            {scan.status === 'done' ? 'Skan zakończony.' : 'Skan zakończony z błędami.'}
          </p>
          <button
            type="button"
            onClick={() => onDone(scanId)}
            className="rounded-md bg-emerald-600 px-4 py-2 font-medium text-slate-950"
          >
            Zobacz raport
          </button>
        </>
      )}
    </div>
  )
}
```

Replace `frontend/src/App.tsx` in full:

```tsx
// frontend/src/App.tsx
import { useState } from 'react'
import { UploadStep } from './steps/UploadStep'
import { ScopeEstimateStep } from './steps/ScopeEstimateStep'
import { ProgressStep } from './steps/ProgressStep'
import { ReportStep } from './steps/ReportStep'

type WizardStep = 'upload' | 'scope' | 'progress' | 'report'

function App() {
  const [step, setStep] = useState<WizardStep>('upload')
  const [file, setFile] = useState<File | null>(null)
  const [scanId, setScanId] = useState<string | null>(null)

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      {step === 'upload' && (
        <UploadStep
          onFileSelected={(selected) => {
            setFile(selected)
            setStep('scope')
          }}
        />
      )}
      {step === 'scope' && file && (
        <ScopeEstimateStep
          file={file}
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

Append a new test to `frontend/src/App.test.tsx` (inside the existing `describe('App (ScanWizard)', ...)` block):

```tsx
  it('shows a button to view the report once the scan is done, and navigates to ReportStep', async () => {
    vi.spyOn(client, 'createScan').mockResolvedValue({
      scan_id: 'scan-1', status: 'estimated', scope_type: 'full',
      total_products: 5, completed_products: 0,
      estimate: {
        queries_without_refresh: 5, queries_with_refresh: 5,
        cost_usd_without_refresh: '0.05', cost_usd_with_refresh: '0.05',
        seconds_without_refresh: 2, seconds_with_refresh: 2,
      },
      overlapping_count: 0, stale_count: 0, warnings: [],
    })
    vi.spyOn(client, 'startScan').mockResolvedValue(undefined)
    vi.spyOn(useScanEventsModule, 'useScanEvents').mockReturnValue({
      scan: {
        scan_id: 'scan-1', status: 'done', scope_type: 'full',
        total_products: 5, completed_products: 5,
        estimate: {
          queries_without_refresh: 5, queries_with_refresh: 5,
          cost_usd_without_refresh: '0.05', cost_usd_with_refresh: '0.05',
          seconds_without_refresh: 2, seconds_with_refresh: 2,
        },
        overlapping_count: 0, stale_count: 0,
      },
      source: 'sse',
      error: null,
    })
    vi.spyOn(client, 'getReportSummary').mockResolvedValue({
      counts: { total: 5, computable: 5, not_checked: 0, no_offer: 0, currency_mismatch: 0, anomaly: 0 },
      category_table: [],
      scenario_matrix: [
        { scenario_pct: '-0.10', avg_margin_pct: '0.0500', profitable_count: 5 },
        { scenario_pct: '-0.05', avg_margin_pct: '0.0800', profitable_count: 5 },
        { scenario_pct: '0.00', avg_margin_pct: '0.1000', profitable_count: 5 },
        { scenario_pct: '0.05', avg_margin_pct: '0.1200', profitable_count: 5 },
      ],
    })
    vi.spyOn(client, 'getReportProducts').mockResolvedValue({ total: 0, page: 1, page_size: 25, rows: [] })

    render(<App />)

    const file = new File(['nazwa;cena'], 'catalog.csv', { type: 'text/csv' })
    await userEvent.upload(screen.getByLabelText(/plik CSV/i), file)
    await userEvent.click(screen.getByRole('button', { name: 'Dalej' }))
    await screen.findByRole('heading', { name: 'Zakres skanu' })
    await userEvent.click(screen.getByRole('button', { name: 'Oszacuj koszt' }))
    await screen.findByText(/bez odświeżania/i)
    await userEvent.click(screen.getByRole('button', { name: 'Uruchom skan' }))
    await screen.findByRole('button', { name: 'Zobacz raport' })

    await userEvent.click(screen.getByRole('button', { name: 'Zobacz raport' }))

    expect(await screen.findByText('+10.0%')).toBeInTheDocument()
  })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS — full suite green (Tasks 1-9 combined).

- [ ] **Step 5: Run the linter**

Run: `cd frontend && npm run lint`
Expected: clean.

- [ ] **Step 6: Run the backend suite once more for a final full-stack check**

Run: `cd backend && python -m pytest`
Expected: all green (2 pre-existing skips expected).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/steps/ProgressStep.tsx frontend/src/steps/ProgressStep.test.tsx frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "Wire ReportStep into the wizard: ProgressStep gains a Zobacz raport button"
```

---

## Self-Review Notes

- **Spec coverage:** `evaluate_record`'s exclusion-reason precedence (Task 1) covers the design
  spec's not-checked/no-offer/currency-mismatch/anomaly bucketing exactly. `build_summary` (Task 3)
  covers the verdict/global-scenario-matrix/category-table-at-0%-reference shape. `list_product_rows`
  (Task 4) covers server-side pagination/filter/sort, required given the ~115k-row catalog. Both
  API endpoints (Task 5) enforce the done/failed-only gate and `Decimal`-safe query parsing. The
  frontend (Tasks 7-8) implements the approved Apple-inspired visual direction: verdict numeral,
  Settings.app-style grouped cost card, card-based scenario matrix, hairline category table, and a
  single responsive (not duplicated) product row component instead of separate desktop/mobile
  markups. Task 9 closes the wizard loop. Explicit recompute (not per-keystroke), `localStorage`
  persistence, and fixed (non-configurable) scenario percentages are all honored throughout.
- **Placeholder scan:** none — every step has complete, runnable code.
- **Type consistency:** `ReportSummary`/`ReportCounts`/`CategoryRow`/`ScenarioRow` (Task 6) mirror
  Task 5's `_summary_to_dict` field-for-field. `ProductRow`/`ProductPage`/`ProductOffer`/
  `MarginResult` (Task 6) mirror Task 5's `_evaluation_to_dict`/`_product_page_to_dict` field-for-
  field, including the `id` field added specifically so the frontend has a collision-free React key
  (an `external_id`-based key would have been unsafe — `external_id` is documented elsewhere in
  this codebase as not guaranteed unique across a scan's products). `CostConfigInput`'s four field
  names (`commissionPct`/`shippingCost`/`vatPct`/`returnsPct`) are used identically in
  `costConfigParams` (Task 6), `ReportStep`'s state (Task 7), and every test's assertions (Tasks
  6-9). `formatPct` is defined once in Task 7 and reused, not redefined, in Task 8.

## Next steps after this plan

Phase 5c (column-mapping correction screen) still needs its own brainstorming session — it
requires a new backend preview endpoint (upload → detected mapping + sample rows, without
committing) that doesn't exist yet, per Phase 4's explicit deferral. The standing, dated commitment
from Handoff 2 remains open: after Phase 5b/5c land and a real scan runs against the user's actual
~115k-row catalog, check the percentage of Perplexity results coming back `found=false` or
low-confidence, and revisit open-web SERP as a supplementary source only if that number is high.
