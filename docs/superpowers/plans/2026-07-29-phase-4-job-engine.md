# Phase 4 — Job Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the asynchronous, resumable, concurrency-limited scan engine that turns an
uploaded CSV catalog into a persisted set of price lookups against Perplexity, with a
cost/time estimate shown before any money is spent, a two-step start (estimate, then confirm),
stale-product detection, and live progress via Server-Sent Events.

**Architecture:** A new `backend/app/scans/` package: pure data models, a SQLite-backed
`ScanStore` (same file as Phase 3's `PriceCache`), a water-filling sampling algorithm, a cost
estimator, staleness detection built directly on `PriceCache.cached_at`, an orchestration
function that ties CSV parsing + scope resolution + estimation together for `POST /scans`, an
async job engine that drains `pending` products through `get_offer_cached` under a
concurrency semaphore, and a thin FastAPI router wiring it all together. One small but
necessary change to already-shipped Phase 3 code: `get_offer_cached` currently swallows
`ProviderUnavailable` and returns `None` — the job engine needs to tell "genuinely no offer
found" apart from "transient failure, retry this product later," so Task 1 changes it to
propagate the exception instead.

**Tech Stack:** Python, `asyncio` (stdlib) for the concurrent worker, `fastapi`'s
`StreamingResponse` for SSE (no new dependency — `sse-starlette` or similar is NOT needed),
stdlib `sqlite3` for persistence (same pattern as `PriceCache`).

## Global Constraints

- Money is always `Decimal`, never `float` (existing project rule).
- No new runtime dependencies — everything in this plan is buildable with what
  `backend/requirements.txt` already has (`fastapi`, `httpx`, stdlib `asyncio`/`sqlite3`).
- Job creation is always **two steps**, never one: `POST /scans` computes and returns a
  cost/time estimate and persists the scan in status `estimated` **without spending any
  money**; a separate `POST /scans/{id}/start` is the only thing that can start actually
  querying Perplexity. This is a hard rule from the design spec ("nie wolno go zaskoczyć") —
  no task in this plan may collapse these into one step.
- Resumability means **crash-resilience only**: if the process restarts mid-scan, calling the
  engine again for the same `scan_id` continues exactly the `pending` products, with no manual
  pause/resume UI. No task should add pause/resume machinery.
- `max_concurrency`, `staleness_threshold_days`, and `max_delivery_days` are all **per-request
  parameters with defaults**, never hardcoded module-level constants that can't be overridden
  (design decision: the user configures these from the UI in Phase 5).
- Never iterate a `dict`/`set` where the resulting order affects a persisted or reproducible
  outcome (e.g. category processing order, remainder distribution) — use a stably sorted list.
  This is a repeat of a Phase 0-2 lesson (`csv.Sniffer`/alias-lookup non-determinism bug).
- Follow existing test conventions: no shared `conftest.py` — each test file defines its own
  local `_make_*(**overrides)` helper.
- Every unit test in this plan runs with **zero real network calls** — the job engine's tests
  use fake/counting providers, exactly like Phase 3.

---

## File Structure

- Modify: `backend/app/providers/lookup.py` — `get_offer_cached` propagates
  `ProviderUnavailable` instead of swallowing it.
- Modify: `backend/tests/providers/test_lookup.py` — update the two tests that currently
  assert the swallowed behavior; add one confirming the cache is still untouched when the
  exception propagates.
- Modify: `backend/app/cache/sqlite_cache.py` — add `PriceCache.invalidate(...)` (deletes one
  cache row), needed so a forced refresh of a stale product actually bypasses the cache.
- Create: `backend/app/scans/__init__.py`
- Create: `backend/app/scans/models.py` — `ScanStatus`, `ProductStatus` enums; `Scan`,
  `ScanProductRecord`, `CostEstimate`, `StalenessReport` dataclasses.
- Create: `backend/app/scans/store.py` — `ScanStore` (SQLite persistence for `scans` and
  `scan_products` tables).
- Create: `backend/app/scans/sampling.py` — `resolve_sample_scope` (water-filling algorithm).
- Create: `backend/app/scans/estimate.py` — `estimate_cost`.
- Create: `backend/app/scans/staleness.py` — `analyze_staleness`.
- Create: `backend/app/scans/orchestration.py` — `create_scan` (ties CSV parsing, scope
  resolution, staleness, estimate, and `ScanStore.create_scan` together).
- Create: `backend/app/scans/engine.py` — `run_scan` (the async worker).
- Create: `backend/app/scans/api.py` — FastAPI `APIRouter` with the four endpoints.
- Modify: `backend/app/main.py` — mount the new router, wire up shared `PriceCache` /
  `ScanStore` / `PerplexityProvider` instances.
- Test: `backend/tests/scans/__init__.py` and one test file per module above, mirroring the
  path (`backend/tests/scans/test_sampling.py`, etc.).

---

## Task 1: Make `get_offer_cached` propagate transient failures

**Files:**
- Modify: `backend/app/providers/lookup.py`
- Modify: `backend/tests/providers/test_lookup.py`

**Interfaces:**
- Consumes: `ProviderUnavailable` from `app.providers.base` (already exists).
- Produces: `get_offer_cached(product, market, max_delivery_days, cache, provider) ->
  OfferResult | None`, now **raising** `ProviderUnavailable` on transient failure instead of
  swallowing it. Used by Task 8's `engine.py` to distinguish "no offer found" (safe to mark
  the product `done`) from "provider unavailable" (leave the product `pending` for a later
  retry — this is the mechanism resumability actually relies on for in-run transient failures,
  not just process crashes).

- [ ] **Step 1: Update the two tests that assert the old swallow-and-return-None behavior**

Replace the two existing tests in `backend/tests/providers/test_lookup.py`:

```python
def test_provider_unavailable_propagates_and_is_not_cached(tmp_path):
    """A transient failure (network error / 429 / 5xx) must not be persisted as
    a 30-day negative result, and the caller must be able to tell it apart from
    a genuine 'no offer found' — see Phase 4's job engine, which retries on this."""
    cache = PriceCache(tmp_path / "cache.sqlite3")
    provider = _UnavailableProvider()
    product = _make_product()

    with pytest.raises(ProviderUnavailable):
        get_offer_cached(product, "PL", 5, cache, provider)

    assert provider.call_count == 1
    # Nothing was written to the cache — a later lookup must retry, not reuse
    # a stale "not found" verdict from the transient failure.
    assert cache.get(product.ean, "PL", "perplexity", 5) is None

    # Confirm it genuinely retries (would be 1 forever if it had been cached).
    with pytest.raises(ProviderUnavailable):
        get_offer_cached(product, "PL", 5, cache, provider)
    assert provider.call_count == 2
    cache.close()


def test_provider_unavailable_propagates_for_product_without_ean(tmp_path):
    cache = PriceCache(tmp_path / "cache.sqlite3")
    provider = _UnavailableProvider()
    product = _make_product(ean=None)

    with pytest.raises(ProviderUnavailable):
        get_offer_cached(product, "PL", 5, cache, provider)

    assert provider.call_count == 1
    cache.close()
```

Add `import pytest` at the top of the file if not already present (check first — it is not,
per the current file).

- [ ] **Step 2: Run the updated tests to verify they fail against the current implementation**

Run: `cd backend && .venv/bin/pytest tests/providers/test_lookup.py -v -k provider_unavailable`
Expected: FAIL — the current code returns `None` instead of raising, so
`pytest.raises(ProviderUnavailable)` never fires.

- [ ] **Step 3: Change `get_offer_cached` to let `ProviderUnavailable` propagate**

```python
# backend/app/providers/lookup.py
from __future__ import annotations

from app.cache.sqlite_cache import PriceCache
from app.models.product import Product
from app.providers.base import OfferResult, PriceProvider


def get_offer_cached(
    product: Product,
    market: str,
    max_delivery_days: int,
    cache: PriceCache,
    provider: PriceProvider,
) -> OfferResult | None:
    if not product.ean:
        return provider.find_cheapest(product, market, max_delivery_days)

    cached = cache.get(product.ean, market, provider.name, max_delivery_days)
    if cached is not None:
        return cached.offer

    offer = provider.find_cheapest(product, market, max_delivery_days)
    cache.set(product.ean, market, provider.name, max_delivery_days, offer)
    return offer
```

(This drops the two `try/except ProviderUnavailable: return None` blocks — `ProviderUnavailable`
now simply propagates out of `provider.find_cheapest`, and since it's raised before
`cache.set(...)` is ever reached, the cache is naturally never written to on that path.)

- [ ] **Step 4: Run the full provider/lookup test suite to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/providers/ -v`
Expected: PASS, all tests including the two updated ones.

- [ ] **Step 5: Commit**

```bash
git add backend/app/providers/lookup.py backend/tests/providers/test_lookup.py
git commit -m "Make get_offer_cached propagate ProviderUnavailable instead of swallowing it"
```

---

## Task 2: Add `PriceCache.invalidate`

**Files:**
- Modify: `backend/app/cache/sqlite_cache.py`
- Modify: `backend/tests/cache/test_sqlite_cache.py`

**Interfaces:**
- Produces: `PriceCache.invalidate(ean: str, market: str, provider: str, max_delivery_days:
  int) -> None` — deletes the matching row if present, does nothing if absent. Used by Task 7's
  `orchestration.py`/Task 9's API layer to force a fresh Perplexity query for a product the
  user explicitly asked to refresh despite an still-valid cache entry.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/cache/test_sqlite_cache.py`:

```python
def test_invalidate_removes_a_cached_entry(tmp_path):
    cache = PriceCache(tmp_path / "cache.sqlite3")
    offer = _make_offer()
    cache.set("5901234123457", "PL", "perplexity", 5, offer)

    cache.invalidate("5901234123457", "PL", "perplexity", 5)

    assert cache.get("5901234123457", "PL", "perplexity", 5) is None
    cache.close()


def test_invalidate_on_missing_entry_is_a_no_op(tmp_path):
    cache = PriceCache(tmp_path / "cache.sqlite3")

    cache.invalidate("5901234123457", "PL", "perplexity", 5)  # must not raise

    assert cache.get("5901234123457", "PL", "perplexity", 5) is None
    cache.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/cache/test_sqlite_cache.py -v -k invalidate`
Expected: FAIL with `AttributeError: 'PriceCache' object has no attribute 'invalidate'`

- [ ] **Step 3: Implement `invalidate`**

Add to `backend/app/cache/sqlite_cache.py`, inside the `PriceCache` class (after `set`, before
`close`):

```python
    def invalidate(
        self, ean: str, market: str, provider: str, max_delivery_days: int
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                DELETE FROM price_cache
                WHERE ean = ? AND market = ? AND provider = ? AND max_delivery_days = ?
                """,
                (ean, market, provider, max_delivery_days),
            )
            self._conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/cache/test_sqlite_cache.py -v`
Expected: PASS, all tests including the two new ones.

- [ ] **Step 5: Commit**

```bash
git add backend/app/cache/sqlite_cache.py backend/tests/cache/test_sqlite_cache.py
git commit -m "Add PriceCache.invalidate for forced-refresh of stale entries"
```

---

## Task 3: Data models

**Files:**
- Create: `backend/app/scans/__init__.py`
- Create: `backend/app/scans/models.py`
- Test: `backend/tests/scans/__init__.py`
- Test: `backend/tests/scans/test_models.py`

**Interfaces:**
- Consumes: nothing new (pure dataclasses/enums).
- Produces:
  - `ScanStatus` enum: `ESTIMATED`, `RUNNING`, `DONE`, `FAILED`.
  - `ProductStatus` enum: `PENDING`, `DONE`, `SKIPPED`.
  - `Scan` frozen dataclass: `id: str`, `status: ScanStatus`, `scope_type: str` (`"full"` or
    `"sample"`), `sample_per_category: int | None`, `market: str`, `max_delivery_days: int`,
    `max_concurrency: int`, `staleness_threshold_days: int`, `total_products: int`,
    `completed_products: int`, `estimate: CostEstimate`, `created_at: float`.
  - `ScanProductRecord` frozen dataclass: `id: int`, `scan_id: str`, `product: Product` (the
    existing `app.models.product.Product`), `status: ProductStatus`, `was_stale: bool`,
    `offer: OfferResult | None`.
  - `CostEstimate` frozen dataclass: `queries_without_refresh: int`, `queries_with_refresh:
    int`, `cost_usd_without_refresh: Decimal`, `cost_usd_with_refresh: Decimal`,
    `seconds_without_refresh: float`, `seconds_with_refresh: float`.
  - `StalenessReport` frozen dataclass: `overlapping_count: int`, `stale_external_ids:
    tuple[str, ...]` (the `external_id`s of products flagged stale, so callers can mark them).
  All four are used by every later task in this plan.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/scans/test_models.py
from decimal import Decimal

from app.models.product import Product
from app.providers.base import OfferResult
from app.scans.models import (
    CostEstimate,
    ProductStatus,
    Scan,
    ScanProductRecord,
    ScanStatus,
    StalenessReport,
)


def _make_product(**overrides) -> Product:
    defaults = dict(
        tenant_id="t1", source="csv", external_id="1", variant_id=None,
        name="Test Product", ean="5901234123457",
        wholesale_price=Decimal("60.00"), currency="PLN", category="Test",
    )
    defaults.update(overrides)
    return Product(**defaults)


def _make_estimate(**overrides) -> CostEstimate:
    defaults = dict(
        queries_without_refresh=10, queries_with_refresh=12,
        cost_usd_without_refresh=Decimal("0.10"), cost_usd_with_refresh=Decimal("0.12"),
        seconds_without_refresh=20.0, seconds_with_refresh=24.0,
    )
    defaults.update(overrides)
    return CostEstimate(**defaults)


def test_scan_status_values():
    assert ScanStatus.ESTIMATED.value == "estimated"
    assert ScanStatus.RUNNING.value == "running"
    assert ScanStatus.DONE.value == "done"
    assert ScanStatus.FAILED.value == "failed"


def test_product_status_values():
    assert ProductStatus.PENDING.value == "pending"
    assert ProductStatus.DONE.value == "done"
    assert ProductStatus.SKIPPED.value == "skipped"


def test_scan_holds_all_fields():
    scan = Scan(
        id="scan-1", status=ScanStatus.ESTIMATED, scope_type="sample",
        sample_per_category=50, market="PL", max_delivery_days=5,
        max_concurrency=5, staleness_threshold_days=14,
        total_products=100, completed_products=0,
        estimate=_make_estimate(), created_at=1700000000.0,
    )
    assert scan.id == "scan-1"
    assert scan.status == ScanStatus.ESTIMATED
    assert scan.scope_type == "sample"
    assert scan.sample_per_category == 50
    assert scan.estimate.queries_without_refresh == 10


def test_scan_product_record_holds_all_fields():
    product = _make_product()
    record = ScanProductRecord(
        id=1, scan_id="scan-1", product=product,
        status=ProductStatus.PENDING, was_stale=False, offer=None,
    )
    assert record.id == 1
    assert record.scan_id == "scan-1"
    assert record.product == product
    assert record.status == ProductStatus.PENDING
    assert record.was_stale is False
    assert record.offer is None


def test_staleness_report_holds_fields():
    report = StalenessReport(overlapping_count=3, stale_external_ids=("1", "2"))
    assert report.overlapping_count == 3
    assert report.stale_external_ids == ("1", "2")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/scans/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.scans'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/scans/__init__.py
```

```python
# backend/app/scans/models.py
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.models.product import Product
from app.providers.base import OfferResult


class ScanStatus(str, Enum):
    ESTIMATED = "estimated"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class ProductStatus(str, Enum):
    PENDING = "pending"
    DONE = "done"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class CostEstimate:
    queries_without_refresh: int
    queries_with_refresh: int
    cost_usd_without_refresh: Decimal
    cost_usd_with_refresh: Decimal
    seconds_without_refresh: float
    seconds_with_refresh: float


@dataclass(frozen=True)
class StalenessReport:
    overlapping_count: int
    stale_external_ids: tuple[str, ...]


@dataclass(frozen=True)
class Scan:
    id: str
    status: ScanStatus
    scope_type: str
    sample_per_category: int | None
    market: str
    max_delivery_days: int
    max_concurrency: int
    staleness_threshold_days: int
    total_products: int
    completed_products: int
    estimate: CostEstimate
    created_at: float


@dataclass(frozen=True)
class ScanProductRecord:
    id: int
    scan_id: str
    product: Product
    status: ProductStatus
    was_stale: bool
    offer: OfferResult | None
```

```python
# backend/tests/scans/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/scans/test_models.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/scans/__init__.py backend/app/scans/models.py backend/tests/scans/__init__.py backend/tests/scans/test_models.py
git commit -m "Add Phase 4 scan data models"
```

---

## Task 4: Water-filling sampling algorithm

**Files:**
- Create: `backend/app/scans/sampling.py`
- Test: `backend/tests/scans/test_sampling.py`

**Interfaces:**
- Consumes: `Product` from `app.models.product`.
- Produces: `resolve_sample_scope(products_by_category: dict[str, list[Product]],
  target_per_category: int, seed: int) -> list[Product]`. Used by Task 7's
  `orchestration.py` when `scope_type == "sample"`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/scans/test_sampling.py
from decimal import Decimal

from app.models.product import Product
from app.scans.sampling import resolve_sample_scope


def _make_products(category: str, count: int, start: int = 0) -> list[Product]:
    return [
        Product(
            tenant_id="t1", source="csv", external_id=f"{category}-{i}", variant_id=None,
            name=f"{category} product {i}", ean=None,
            wholesale_price=Decimal("10.00"), currency="PLN", category=category,
        )
        for i in range(start, start + count)
    ]


def test_exact_fit_takes_target_from_each_category():
    products_by_category = {
        "A": _make_products("A", 50),
        "B": _make_products("B", 50),
    }

    result = resolve_sample_scope(products_by_category, target_per_category=50, seed=1)

    assert len(result) == 100


def test_short_category_donates_shortfall_to_pool_evenly():
    # A has only 20 (target 50) -> shortfall of 30 goes into the pool, split evenly
    # between B and C (both comfortably over target), 15 each.
    products_by_category = {
        "A": _make_products("A", 20),
        "B": _make_products("B", 200),
        "C": _make_products("C", 200),
    }

    result = resolve_sample_scope(products_by_category, target_per_category=50, seed=1)

    by_category: dict[str, int] = {}
    for p in result:
        by_category[p.category] = by_category.get(p.category, 0) + 1

    assert by_category["A"] == 20  # took everything, couldn't hit target
    assert by_category["B"] == 65  # 50 + 15 from the pool
    assert by_category["C"] == 65  # 50 + 15 from the pool
    assert len(result) == 150


def test_uneven_pool_remainder_is_dropped_deterministically():
    # A has 0 (shortfall = target, e.g. 10) -> pool = 10, split between 3
    # over-target categories (B, C, D): 10 // 3 = 3 each, remainder 1 goes to
    # the alphabetically-first category with room (B), C and D get nothing extra.
    products_by_category = {
        "A": [],
        "B": _make_products("B", 100),
        "C": _make_products("C", 100),
        "D": _make_products("D", 100),
    }

    result = resolve_sample_scope(products_by_category, target_per_category=10, seed=1)

    by_category: dict[str, int] = {}
    for p in result:
        by_category[p.category] = by_category.get(p.category, 0) + 1

    assert "A" not in by_category  # took everything (zero), nothing to include
    assert by_category["B"] == 14  # 10 + 3 (share) + 1 (remainder, first alphabetically)
    assert by_category["C"] == 13  # 10 + 3 (share)
    assert by_category["D"] == 13  # 10 + 3 (share)
    assert len(result) == 40


def test_multi_round_redistribution_when_a_category_overflows_its_own_size():
    # A: 0 (shortfall 10). B: 12 (just over target of 10, only 2 spare capacity).
    # C: 100 (plenty of room).
    # Pool = 10, split evenly between B and C (5 each) in round 1: B would need
    # 10+5=15 but only has 12 -> caps at 12 (donates 3 back to the pool), C
    # takes 10+5=15. Pool after round 1 = 3, only C has room left -> C takes all 3.
    # Final: A=0, B=12, C=18.
    products_by_category = {
        "A": [],
        "B": _make_products("B", 12),
        "C": _make_products("C", 100),
    }

    result = resolve_sample_scope(products_by_category, target_per_category=10, seed=1)

    by_category: dict[str, int] = {}
    for p in result:
        by_category[p.category] = by_category.get(p.category, 0) + 1

    assert "A" not in by_category
    assert by_category["B"] == 12
    assert by_category["C"] == 18
    assert len(result) == 30


def test_same_seed_gives_same_sample_twice():
    products_by_category = {"A": _make_products("A", 200)}

    first = resolve_sample_scope(products_by_category, target_per_category=10, seed=42)
    second = resolve_sample_scope(products_by_category, target_per_category=10, seed=42)

    assert [p.external_id for p in first] == [p.external_id for p in second]


def test_different_seed_can_give_a_different_sample():
    products_by_category = {"A": _make_products("A", 200)}

    first = resolve_sample_scope(products_by_category, target_per_category=10, seed=1)
    second = resolve_sample_scope(products_by_category, target_per_category=10, seed=2)

    # Not a hard guarantee for any possible RNG, but true for Python's Random
    # with these seeds and this sample size — a meaningful smoke check that the
    # seed actually participates in the selection.
    assert [p.external_id for p in first] != [p.external_id for p in second]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/scans/test_sampling.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.scans.sampling'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/scans/sampling.py
from __future__ import annotations

import random

from app.models.product import Product


def resolve_sample_scope(
    products_by_category: dict[str, list[Product]],
    target_per_category: int,
    seed: int,
) -> list[Product]:
    category_names = sorted(products_by_category.keys())
    sizes = {name: len(products_by_category[name]) for name in category_names}

    allocation: dict[str, int] = {}
    over_target: list[str] = []
    pool = 0

    for name in category_names:
        size = sizes[name]
        if size <= target_per_category:
            allocation[name] = size
            pool += target_per_category - size
        else:
            allocation[name] = target_per_category
            over_target.append(name)

    while pool > 0 and over_target:
        share, remainder = divmod(pool, len(over_target))

        if share == 0:
            for name in over_target[:remainder]:
                allocation[name] += 1
            break

        pool = remainder
        still_over_target: list[str] = []
        for name in over_target:
            size = sizes[name]
            candidate_allocation = allocation[name] + share
            if candidate_allocation >= size:
                pool += candidate_allocation - size
                allocation[name] = size
            else:
                allocation[name] = candidate_allocation
                still_over_target.append(name)
        over_target = still_over_target

    rng = random.Random(seed)
    selected: list[Product] = []
    for name in category_names:
        candidates = products_by_category[name]
        count = allocation[name]
        if count >= len(candidates):
            selected.extend(candidates)
        else:
            selected.extend(rng.sample(candidates, count))
    return selected
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/scans/test_sampling.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/scans/sampling.py backend/tests/scans/test_sampling.py
git commit -m "Add water-filling sampling algorithm for category-proportional scans"
```

---

## Task 5: Cost/time estimator

**Files:**
- Create: `backend/app/scans/estimate.py`
- Test: `backend/tests/scans/test_estimate.py`

**Interfaces:**
- Consumes: `CostEstimate` from Task 3's `app.scans.models`.
- Produces: `estimate_cost(cache_misses: int, stale_count: int, max_concurrency: int) ->
  CostEstimate`. Used by Task 7's `orchestration.py`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/scans/test_estimate.py
from decimal import Decimal

from app.scans.estimate import COST_PER_QUERY_USD, SECONDS_PER_QUERY, estimate_cost


def test_estimate_with_no_misses_and_no_stale_is_free_and_instant():
    result = estimate_cost(cache_misses=0, stale_count=0, max_concurrency=5)

    assert result.queries_without_refresh == 0
    assert result.queries_with_refresh == 0
    assert result.cost_usd_without_refresh == Decimal("0.00")
    assert result.cost_usd_with_refresh == Decimal("0.00")
    assert result.seconds_without_refresh == 0.0
    assert result.seconds_with_refresh == 0.0


def test_estimate_scales_with_query_count_and_concurrency():
    result = estimate_cost(cache_misses=100, stale_count=20, max_concurrency=10)

    assert result.queries_without_refresh == 100
    assert result.queries_with_refresh == 120
    assert result.cost_usd_without_refresh == (COST_PER_QUERY_USD * 100).quantize(Decimal("0.01"))
    assert result.cost_usd_with_refresh == (COST_PER_QUERY_USD * 120).quantize(Decimal("0.01"))
    assert result.seconds_without_refresh == (100 / 10) * SECONDS_PER_QUERY
    assert result.seconds_with_refresh == (120 / 10) * SECONDS_PER_QUERY


def test_estimate_with_refresh_is_never_cheaper_than_without():
    result = estimate_cost(cache_misses=50, stale_count=5, max_concurrency=5)

    assert result.queries_with_refresh >= result.queries_without_refresh
    assert result.cost_usd_with_refresh >= result.cost_usd_without_refresh
    assert result.seconds_with_refresh >= result.seconds_without_refresh
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/scans/test_estimate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.scans.estimate'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/scans/estimate.py
from __future__ import annotations

from decimal import Decimal

from app.scans.models import CostEstimate

# Documented assumption, not a measured guarantee — Perplexity's own published
# range is $5-14 per 1000 requests plus token cost (see the Phase 3 design
# spec's research notes); this is a conservative midpoint used only to give
# the user a ballpark before they commit to a scan, not a billing guarantee.
COST_PER_QUERY_USD = Decimal("0.010")

# Rough average latency observed during Phase 3's real Perplexity smoke test
# (~2.36s for one request); used only for the pre-scan time estimate, not a
# guaranteed throughput figure.
SECONDS_PER_QUERY = 2.5


def estimate_cost(cache_misses: int, stale_count: int, max_concurrency: int) -> CostEstimate:
    queries_without_refresh = cache_misses
    queries_with_refresh = cache_misses + stale_count

    return CostEstimate(
        queries_without_refresh=queries_without_refresh,
        queries_with_refresh=queries_with_refresh,
        cost_usd_without_refresh=(COST_PER_QUERY_USD * queries_without_refresh).quantize(Decimal("0.01")),
        cost_usd_with_refresh=(COST_PER_QUERY_USD * queries_with_refresh).quantize(Decimal("0.01")),
        seconds_without_refresh=(queries_without_refresh / max_concurrency) * SECONDS_PER_QUERY,
        seconds_with_refresh=(queries_with_refresh / max_concurrency) * SECONDS_PER_QUERY,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/scans/test_estimate.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/scans/estimate.py backend/tests/scans/test_estimate.py
git commit -m "Add pre-scan cost/time estimator"
```

---

## Task 6: Staleness detection

**Files:**
- Create: `backend/app/scans/staleness.py`
- Test: `backend/tests/scans/test_staleness.py`

**Interfaces:**
- Consumes: `PriceCache` from `app.cache.sqlite_cache`, `Product` from `app.models.product`,
  `StalenessReport` from Task 3's `app.scans.models`.
- Produces: `analyze_staleness(products: list[Product], cache: PriceCache, market: str,
  provider_name: str, max_delivery_days: int, staleness_threshold_days: int) ->
  StalenessReport`. Used by Task 7's `orchestration.py`.

Staleness is computed directly against `PriceCache.cached_at` — a product "overlaps" a
previous scan if it already has a cache entry at all (any age within the cache's own 30-day
TTL); it's "stale" if that entry is older than `staleness_threshold_days`. This deliberately
reuses Phase 3's existing cache rather than tracking cross-scan product history: a product
older than the cache's hard TTL is already a cache miss by the time any of this runs, so it's
naturally re-queried through the normal `get_offer_cached` path regardless — the staleness
threshold only matters for the window *inside* the TTL, which is exactly the "still valid but
the user wants to double-check" scenario this feature targets. Products without an `ean` are
never counted (nothing to look up in the cache).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/scans/test_staleness.py
import time
from decimal import Decimal

from app.cache.sqlite_cache import PriceCache
from app.models.product import Product
from app.providers.base import OfferResult
from app.scans.staleness import analyze_staleness


def _make_product(**overrides) -> Product:
    defaults = dict(
        tenant_id="t1", source="csv", external_id="1", variant_id=None,
        name="Test Product", ean="5901234123457",
        wholesale_price=Decimal("60.00"), currency="PLN", category="Test",
    )
    defaults.update(overrides)
    return Product(**defaults)


def _make_offer(**overrides) -> OfferResult:
    defaults = dict(
        price=Decimal("89.99"), currency="PLN", seller="Example Shop",
        source_url="https://example.com/product", delivery_days=2,
        confidence=0.85, citations=("https://example.com/product",),
        raw_response="{}",
    )
    defaults.update(overrides)
    return OfferResult(**defaults)


def test_product_with_no_prior_cache_entry_is_not_overlapping(tmp_path):
    cache = PriceCache(tmp_path / "cache.sqlite3")
    product = _make_product()

    report = analyze_staleness([product], cache, "PL", "perplexity", 5, staleness_threshold_days=14)

    assert report.overlapping_count == 0
    assert report.stale_external_ids == ()
    cache.close()


def test_product_with_fresh_cache_entry_overlaps_but_is_not_stale(tmp_path):
    cache = PriceCache(tmp_path / "cache.sqlite3")
    product = _make_product()
    cache.set(product.ean, "PL", "perplexity", 5, _make_offer())

    report = analyze_staleness([product], cache, "PL", "perplexity", 5, staleness_threshold_days=14)

    assert report.overlapping_count == 1
    assert report.stale_external_ids == ()
    cache.close()


def test_product_with_old_cache_entry_is_stale(tmp_path):
    cache = PriceCache(tmp_path / "cache.sqlite3")
    product = _make_product()
    cache.set(product.ean, "PL", "perplexity", 5, _make_offer())
    # Backdate the cached_at timestamp directly (simulates 20 days ago; still
    # within the cache's 30-day TTL, so cache.get() still returns it).
    twenty_days_ago = time.time() - (20 * 24 * 3600)
    cache._conn.execute(
        "UPDATE price_cache SET cached_at = ? WHERE ean = ?", (twenty_days_ago, product.ean)
    )
    cache._conn.commit()

    report = analyze_staleness([product], cache, "PL", "perplexity", 5, staleness_threshold_days=14)

    assert report.overlapping_count == 1
    assert report.stale_external_ids == (product.external_id,)
    cache.close()


def test_product_without_ean_is_never_counted(tmp_path):
    cache = PriceCache(tmp_path / "cache.sqlite3")
    product = _make_product(ean=None)

    report = analyze_staleness([product], cache, "PL", "perplexity", 5, staleness_threshold_days=14)

    assert report.overlapping_count == 0
    assert report.stale_external_ids == ()
    cache.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/scans/test_staleness.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.scans.staleness'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/scans/staleness.py
from __future__ import annotations

import time

from app.cache.sqlite_cache import PriceCache
from app.models.product import Product
from app.scans.models import StalenessReport


def analyze_staleness(
    products: list[Product],
    cache: PriceCache,
    market: str,
    provider_name: str,
    max_delivery_days: int,
    staleness_threshold_days: int,
) -> StalenessReport:
    threshold_seconds = staleness_threshold_days * 24 * 3600
    now = time.time()

    overlapping_count = 0
    stale_external_ids: list[str] = []

    for product in products:
        if not product.ean:
            continue
        entry = cache.get(product.ean, market, provider_name, max_delivery_days)
        if entry is None:
            continue
        overlapping_count += 1
        if now - entry.cached_at > threshold_seconds:
            stale_external_ids.append(product.external_id)

    return StalenessReport(
        overlapping_count=overlapping_count,
        stale_external_ids=tuple(stale_external_ids),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/scans/test_staleness.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/scans/staleness.py backend/tests/scans/test_staleness.py
git commit -m "Add staleness detection against PriceCache.cached_at"
```

---

## Task 7: `ScanStore` — SQLite persistence

**Files:**
- Create: `backend/app/scans/store.py`
- Test: `backend/tests/scans/test_store.py`

**Interfaces:**
- Consumes: `Scan`, `ScanProductRecord`, `ScanStatus`, `ProductStatus`, `CostEstimate` from
  Task 3; `Product` from `app.models.product`; `OfferResult` from `app.providers.base`.
- Produces: `ScanStore` class with:
  - `__init__(self, db_path: str | Path)`
  - `create_scan(self, *, scope_type: str, sample_per_category: int | None, market: str,
    max_delivery_days: int, max_concurrency: int, staleness_threshold_days: int, products:
    list[Product], stale_external_ids: tuple[str, ...], estimate: CostEstimate) -> str` —
    returns the new `scan_id`; persists the scan row (status `ESTIMATED`) and one
    `scan_products` row per product (status `PENDING`, `was_stale` set from
    `stale_external_ids`).
  - `get_scan(self, scan_id: str) -> Scan | None`
  - `start_scan(self, scan_id: str) -> None` — sets status to `RUNNING`.
  - `finalize_scan(self, scan_id: str) -> None` — sets status to `DONE` if no `PENDING`
    products remain for this scan, else `FAILED` (meaning: incomplete, needs another
    `run_scan` call to finish the remaining `pending` items).
  - `list_pending(self, scan_id: str) -> list[ScanProductRecord]`
  - `mark_done(self, record_id: int, offer: OfferResult | None) -> None`
  - `mark_skipped(self, record_id: int, offer: OfferResult | None) -> None`
  - `close(self) -> None`
  All used by Task 8's `engine.py`, Task 9's `orchestration.py`, and Task 10's `api.py`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/scans/test_store.py
from decimal import Decimal

from app.models.product import Product
from app.providers.base import OfferResult
from app.scans.estimate import estimate_cost
from app.scans.models import ProductStatus, ScanStatus
from app.scans.store import ScanStore


def _make_product(**overrides) -> Product:
    defaults = dict(
        tenant_id="t1", source="csv", external_id="1", variant_id=None,
        name="Test Product", ean="5901234123457",
        wholesale_price=Decimal("60.00"), currency="PLN", category="Test",
    )
    defaults.update(overrides)
    return Product(**defaults)


def _make_offer(**overrides) -> OfferResult:
    defaults = dict(
        price=Decimal("89.99"), currency="PLN", seller="Example Shop",
        source_url="https://example.com/product", delivery_days=2,
        confidence=0.85, citations=("https://example.com/product",),
        raw_response="{}",
    )
    defaults.update(overrides)
    return OfferResult(**defaults)


def test_create_scan_persists_scan_and_products(tmp_path):
    store = ScanStore(tmp_path / "app.sqlite3")
    products = [_make_product(external_id="1"), _make_product(external_id="2", ean=None)]
    estimate = estimate_cost(cache_misses=2, stale_count=0, max_concurrency=5)

    scan_id = store.create_scan(
        scope_type="full", sample_per_category=None, market="PL", max_delivery_days=5,
        max_concurrency=5, staleness_threshold_days=14,
        products=products, stale_external_ids=(), estimate=estimate,
    )

    scan = store.get_scan(scan_id)
    assert scan is not None
    assert scan.status == ScanStatus.ESTIMATED
    assert scan.total_products == 2
    assert scan.completed_products == 0
    assert scan.estimate.queries_without_refresh == 2

    pending = store.list_pending(scan_id)
    assert len(pending) == 2
    assert {p.product.external_id for p in pending} == {"1", "2"}
    assert all(p.status == ProductStatus.PENDING for p in pending)
    store.close()


def test_stale_products_are_flagged_on_creation(tmp_path):
    store = ScanStore(tmp_path / "app.sqlite3")
    products = [_make_product(external_id="1"), _make_product(external_id="2")]
    estimate = estimate_cost(cache_misses=1, stale_count=1, max_concurrency=5)

    scan_id = store.create_scan(
        scope_type="full", sample_per_category=None, market="PL", max_delivery_days=5,
        max_concurrency=5, staleness_threshold_days=14,
        products=products, stale_external_ids=("2",), estimate=estimate,
    )

    pending = {p.product.external_id: p for p in store.list_pending(scan_id)}
    assert pending["1"].was_stale is False
    assert pending["2"].was_stale is True
    store.close()


def test_get_scan_returns_none_for_unknown_id(tmp_path):
    store = ScanStore(tmp_path / "app.sqlite3")
    assert store.get_scan("does-not-exist") is None
    store.close()


def test_start_scan_sets_status_running(tmp_path):
    store = ScanStore(tmp_path / "app.sqlite3")
    estimate = estimate_cost(cache_misses=1, stale_count=0, max_concurrency=5)
    scan_id = store.create_scan(
        scope_type="full", sample_per_category=None, market="PL", max_delivery_days=5,
        max_concurrency=5, staleness_threshold_days=14,
        products=[_make_product()], stale_external_ids=(), estimate=estimate,
    )

    store.start_scan(scan_id)

    assert store.get_scan(scan_id).status == ScanStatus.RUNNING
    store.close()


def test_mark_done_updates_status_offer_and_progress_count(tmp_path):
    store = ScanStore(tmp_path / "app.sqlite3")
    estimate = estimate_cost(cache_misses=1, stale_count=0, max_concurrency=5)
    scan_id = store.create_scan(
        scope_type="full", sample_per_category=None, market="PL", max_delivery_days=5,
        max_concurrency=5, staleness_threshold_days=14,
        products=[_make_product()], stale_external_ids=(), estimate=estimate,
    )
    record = store.list_pending(scan_id)[0]
    offer = _make_offer()

    store.mark_done(record.id, offer)

    assert store.list_pending(scan_id) == []
    assert store.get_scan(scan_id).completed_products == 1
    store.close()


def test_mark_skipped_updates_status_and_progress_without_counting_as_pending(tmp_path):
    store = ScanStore(tmp_path / "app.sqlite3")
    estimate = estimate_cost(cache_misses=0, stale_count=1, max_concurrency=5)
    scan_id = store.create_scan(
        scope_type="full", sample_per_category=None, market="PL", max_delivery_days=5,
        max_concurrency=5, staleness_threshold_days=14,
        products=[_make_product()], stale_external_ids=("1",), estimate=estimate,
    )
    record = store.list_pending(scan_id)[0]
    offer = _make_offer()

    store.mark_skipped(record.id, offer)

    assert store.list_pending(scan_id) == []
    assert store.get_scan(scan_id).completed_products == 1
    store.close()


def test_finalize_scan_is_done_when_nothing_pending(tmp_path):
    store = ScanStore(tmp_path / "app.sqlite3")
    estimate = estimate_cost(cache_misses=1, stale_count=0, max_concurrency=5)
    scan_id = store.create_scan(
        scope_type="full", sample_per_category=None, market="PL", max_delivery_days=5,
        max_concurrency=5, staleness_threshold_days=14,
        products=[_make_product()], stale_external_ids=(), estimate=estimate,
    )
    store.mark_done(store.list_pending(scan_id)[0].id, _make_offer())

    store.finalize_scan(scan_id)

    assert store.get_scan(scan_id).status == ScanStatus.DONE
    store.close()


def test_finalize_scan_is_failed_when_products_still_pending(tmp_path):
    store = ScanStore(tmp_path / "app.sqlite3")
    estimate = estimate_cost(cache_misses=2, stale_count=0, max_concurrency=5)
    scan_id = store.create_scan(
        scope_type="full", sample_per_category=None, market="PL", max_delivery_days=5,
        max_concurrency=5, staleness_threshold_days=14,
        products=[_make_product(external_id="1"), _make_product(external_id="2")],
        stale_external_ids=(), estimate=estimate,
    )
    store.mark_done(store.list_pending(scan_id)[0].id, _make_offer())
    # One product ("2") is still pending.

    store.finalize_scan(scan_id)

    assert store.get_scan(scan_id).status == ScanStatus.FAILED
    store.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/scans/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.scans.store'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/scans/store.py
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from decimal import Decimal
from pathlib import Path

from app.models.product import Product
from app.providers.base import OfferResult
from app.scans.models import (
    CostEstimate,
    ProductStatus,
    Scan,
    ScanProductRecord,
    ScanStatus,
)


class ScanStore:
    def __init__(self, db_path: str | Path):
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._create_schema()

    def _create_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scans (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                scope_type TEXT NOT NULL,
                sample_per_category INTEGER,
                market TEXT NOT NULL,
                max_delivery_days INTEGER NOT NULL,
                max_concurrency INTEGER NOT NULL,
                staleness_threshold_days INTEGER NOT NULL,
                total_products INTEGER NOT NULL,
                queries_without_refresh INTEGER NOT NULL,
                queries_with_refresh INTEGER NOT NULL,
                cost_usd_without_refresh TEXT NOT NULL,
                cost_usd_with_refresh TEXT NOT NULL,
                seconds_without_refresh REAL NOT NULL,
                seconds_with_refresh REAL NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                source TEXT NOT NULL,
                external_id TEXT NOT NULL,
                variant_id TEXT,
                name TEXT NOT NULL,
                ean TEXT,
                wholesale_price TEXT NOT NULL,
                currency TEXT NOT NULL,
                category TEXT NOT NULL,
                status TEXT NOT NULL,
                was_stale INTEGER NOT NULL,
                offer_price TEXT,
                offer_currency TEXT,
                offer_seller TEXT,
                offer_source_url TEXT,
                offer_delivery_days INTEGER,
                offer_confidence REAL,
                offer_citations TEXT,
                offer_raw_response TEXT
            )
            """
        )
        self._conn.commit()

    def create_scan(
        self,
        *,
        scope_type: str,
        sample_per_category: int | None,
        market: str,
        max_delivery_days: int,
        max_concurrency: int,
        staleness_threshold_days: int,
        products: list[Product],
        stale_external_ids: tuple[str, ...],
        estimate: CostEstimate,
    ) -> str:
        scan_id = str(uuid.uuid4())
        stale_set = set(stale_external_ids)
        self._conn.execute(
            """
            INSERT INTO scans (
                id, status, scope_type, sample_per_category, market, max_delivery_days,
                max_concurrency, staleness_threshold_days, total_products,
                queries_without_refresh, queries_with_refresh,
                cost_usd_without_refresh, cost_usd_with_refresh,
                seconds_without_refresh, seconds_with_refresh, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scan_id, ScanStatus.ESTIMATED.value, scope_type, sample_per_category,
                market, max_delivery_days, max_concurrency, staleness_threshold_days,
                len(products), estimate.queries_without_refresh, estimate.queries_with_refresh,
                str(estimate.cost_usd_without_refresh), str(estimate.cost_usd_with_refresh),
                estimate.seconds_without_refresh, estimate.seconds_with_refresh, time.time(),
            ),
        )
        for product in products:
            self._conn.execute(
                """
                INSERT INTO scan_products (
                    scan_id, tenant_id, source, external_id, variant_id, name, ean,
                    wholesale_price, currency, category, status, was_stale
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scan_id, product.tenant_id, product.source, product.external_id,
                    product.variant_id, product.name, product.ean,
                    str(product.wholesale_price), product.currency, product.category,
                    ProductStatus.PENDING.value,
                    1 if product.external_id in stale_set else 0,
                ),
            )
        self._conn.commit()
        return scan_id

    def get_scan(self, scan_id: str) -> Scan | None:
        row = self._conn.execute(
            """
            SELECT status, scope_type, sample_per_category, market, max_delivery_days,
                   max_concurrency, staleness_threshold_days, total_products,
                   queries_without_refresh, queries_with_refresh,
                   cost_usd_without_refresh, cost_usd_with_refresh,
                   seconds_without_refresh, seconds_with_refresh, created_at
            FROM scans WHERE id = ?
            """,
            (scan_id,),
        ).fetchone()
        if row is None:
            return None
        (
            status, scope_type, sample_per_category, market, max_delivery_days,
            max_concurrency, staleness_threshold_days, total_products,
            queries_without_refresh, queries_with_refresh,
            cost_usd_without_refresh, cost_usd_with_refresh,
            seconds_without_refresh, seconds_with_refresh, created_at,
        ) = row

        completed_products = self._conn.execute(
            "SELECT COUNT(*) FROM scan_products WHERE scan_id = ? AND status != ?",
            (scan_id, ProductStatus.PENDING.value),
        ).fetchone()[0]

        return Scan(
            id=scan_id,
            status=ScanStatus(status),
            scope_type=scope_type,
            sample_per_category=sample_per_category,
            market=market,
            max_delivery_days=max_delivery_days,
            max_concurrency=max_concurrency,
            staleness_threshold_days=staleness_threshold_days,
            total_products=total_products,
            completed_products=completed_products,
            estimate=CostEstimate(
                queries_without_refresh=queries_without_refresh,
                queries_with_refresh=queries_with_refresh,
                cost_usd_without_refresh=Decimal(cost_usd_without_refresh),
                cost_usd_with_refresh=Decimal(cost_usd_with_refresh),
                seconds_without_refresh=seconds_without_refresh,
                seconds_with_refresh=seconds_with_refresh,
            ),
            created_at=created_at,
        )

    def start_scan(self, scan_id: str) -> None:
        self._conn.execute(
            "UPDATE scans SET status = ? WHERE id = ?", (ScanStatus.RUNNING.value, scan_id)
        )
        self._conn.commit()

    def finalize_scan(self, scan_id: str) -> None:
        remaining = self._conn.execute(
            "SELECT COUNT(*) FROM scan_products WHERE scan_id = ? AND status = ?",
            (scan_id, ProductStatus.PENDING.value),
        ).fetchone()[0]
        status = ScanStatus.DONE.value if remaining == 0 else ScanStatus.FAILED.value
        self._conn.execute("UPDATE scans SET status = ? WHERE id = ?", (status, scan_id))
        self._conn.commit()

    def list_pending(self, scan_id: str) -> list[ScanProductRecord]:
        rows = self._conn.execute(
            """
            SELECT id, tenant_id, source, external_id, variant_id, name, ean,
                   wholesale_price, currency, category, was_stale
            FROM scan_products WHERE scan_id = ? AND status = ?
            """,
            (scan_id, ProductStatus.PENDING.value),
        ).fetchall()
        return [self._row_to_record(scan_id, row) for row in rows]

    def _row_to_record(self, scan_id: str, row: tuple) -> ScanProductRecord:
        (
            record_id, tenant_id, source, external_id, variant_id, name, ean,
            wholesale_price, currency, category, was_stale,
        ) = row
        product = Product(
            tenant_id=tenant_id, source=source, external_id=external_id,
            variant_id=variant_id, name=name, ean=ean,
            wholesale_price=Decimal(wholesale_price), currency=currency, category=category,
        )
        return ScanProductRecord(
            id=record_id, scan_id=scan_id, product=product,
            status=ProductStatus.PENDING, was_stale=bool(was_stale), offer=None,
        )

    def _mark(self, record_id: int, status: ProductStatus, offer: OfferResult | None) -> None:
        if offer is None:
            self._conn.execute(
                "UPDATE scan_products SET status = ? WHERE id = ?",
                (status.value, record_id),
            )
        else:
            self._conn.execute(
                """
                UPDATE scan_products SET
                    status = ?, offer_price = ?, offer_currency = ?, offer_seller = ?,
                    offer_source_url = ?, offer_delivery_days = ?, offer_confidence = ?,
                    offer_citations = ?, offer_raw_response = ?
                WHERE id = ?
                """,
                (
                    status.value, str(offer.price), offer.currency, offer.seller,
                    offer.source_url, offer.delivery_days, offer.confidence,
                    json.dumps(list(offer.citations)), offer.raw_response, record_id,
                ),
            )
        self._conn.commit()

    def mark_done(self, record_id: int, offer: OfferResult | None) -> None:
        self._mark(record_id, ProductStatus.DONE, offer)

    def mark_skipped(self, record_id: int, offer: OfferResult | None) -> None:
        self._mark(record_id, ProductStatus.SKIPPED, offer)

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/scans/test_store.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/scans/store.py backend/tests/scans/test_store.py
git commit -m "Add ScanStore for persisting scans and their products"
```

---

## Task 8: Scan creation orchestration

**Files:**
- Create: `backend/app/scans/orchestration.py`
- Test: `backend/tests/scans/test_orchestration.py`

**Interfaces:**
- Consumes: `CsvCatalogSource` from `app.sources.csv_source`, `group_by_category` from
  `app.normalize.grouping`, `resolve_sample_scope` from Task 4, `analyze_staleness` from
  Task 6, `estimate_cost` from Task 5, `ScanStore` from Task 7, `PriceCache` from
  `app.cache.sqlite_cache`.
- Produces: `create_scan(*, csv_bytes: bytes, tenant_id: str, scope_type: str,
  sample_per_category: int | None, sample_seed: int, market: str, max_delivery_days: int,
  max_concurrency: int, staleness_threshold_days: int, store: ScanStore, cache: PriceCache,
  provider_name: str) -> str` — returns the new `scan_id`. Used by Task 10's `api.py` for
  `POST /scans`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/scans/test_orchestration.py
from decimal import Decimal

from app.cache.sqlite_cache import PriceCache
from app.providers.base import OfferResult
from app.scans.models import ScanStatus
from app.scans.orchestration import create_scan
from app.scans.store import ScanStore

CSV_BYTES = (
    "nazwa;cena;ean;kategoria\n"
    "Produkt A;10,00;5901234123457;Elektronika\n"
    "Produkt B;20,00;5900000000009;Dom\n"
).encode("utf-8")


def _make_offer(**overrides) -> OfferResult:
    defaults = dict(
        price=Decimal("15.00"), currency="PLN", seller="Example Shop",
        source_url="https://example.com/product", delivery_days=2,
        confidence=0.85, citations=("https://example.com/product",),
        raw_response="{}",
    )
    defaults.update(overrides)
    return OfferResult(**defaults)


def test_create_scan_full_scope_persists_all_products_and_estimates_cost(tmp_path):
    store = ScanStore(tmp_path / "app.sqlite3")
    cache = PriceCache(tmp_path / "app.sqlite3")

    scan_id = create_scan(
        csv_bytes=CSV_BYTES, tenant_id="t1", scope_type="full", sample_per_category=None,
        sample_seed=1, market="PL", max_delivery_days=5, max_concurrency=5,
        staleness_threshold_days=14, store=store, cache=cache, provider_name="perplexity",
    )

    scan = store.get_scan(scan_id)
    assert scan is not None
    assert scan.status == ScanStatus.ESTIMATED
    assert scan.total_products == 2
    assert scan.estimate.queries_without_refresh == 2  # neither EAN cached yet
    store.close()
    cache.close()


def test_create_scan_detects_overlap_and_staleness_against_existing_cache(tmp_path):
    store = ScanStore(tmp_path / "app.sqlite3")
    cache = PriceCache(tmp_path / "app.sqlite3")
    cache.set("5901234123457", "PL", "perplexity", 5, _make_offer())

    scan_id = create_scan(
        csv_bytes=CSV_BYTES, tenant_id="t1", scope_type="full", sample_per_category=None,
        sample_seed=1, market="PL", max_delivery_days=5, max_concurrency=5,
        staleness_threshold_days=14, store=store, cache=cache, provider_name="perplexity",
    )

    scan = store.get_scan(scan_id)
    # One product already has a fresh cache entry -> only 1 real query needed.
    assert scan.estimate.queries_without_refresh == 1
    store.close()
    cache.close()


def test_create_scan_sample_scope_applies_water_filling(tmp_path):
    store = ScanStore(tmp_path / "app.sqlite3")
    cache = PriceCache(tmp_path / "app.sqlite3")

    scan_id = create_scan(
        csv_bytes=CSV_BYTES, tenant_id="t1", scope_type="sample", sample_per_category=1,
        sample_seed=1, market="PL", max_delivery_days=5, max_concurrency=5,
        staleness_threshold_days=14, store=store, cache=cache, provider_name="perplexity",
    )

    scan = store.get_scan(scan_id)
    # Both categories ("Elektronika", "Dom") have exactly 1 product each, and
    # the target is 1 per category -> both are fully included either way.
    assert scan.total_products == 2
    store.close()
    cache.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/scans/test_orchestration.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.scans.orchestration'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/scans/orchestration.py
from __future__ import annotations

from app.cache.sqlite_cache import PriceCache
from app.normalize.grouping import group_by_category
from app.scans.estimate import estimate_cost
from app.scans.sampling import resolve_sample_scope
from app.scans.staleness import analyze_staleness
from app.scans.store import ScanStore
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
) -> str:
    source = CsvCatalogSource(csv_bytes, tenant_id=tenant_id)
    all_products = source.fetch_products()

    if scope_type == "sample":
        assert sample_per_category is not None
        products_by_category = group_by_category(all_products)
        scoped_products = resolve_sample_scope(
            products_by_category, sample_per_category, sample_seed
        )
    else:
        scoped_products = all_products

    staleness = analyze_staleness(
        scoped_products, cache, market, provider_name, max_delivery_days,
        staleness_threshold_days,
    )

    cache_misses = sum(
        1 for p in scoped_products
        if p.ean is None or cache.get(p.ean, market, provider_name, max_delivery_days) is None
    )
    estimate = estimate_cost(
        cache_misses=cache_misses,
        stale_count=len(staleness.stale_external_ids),
        max_concurrency=max_concurrency,
    )

    return store.create_scan(
        scope_type=scope_type,
        sample_per_category=sample_per_category,
        market=market,
        max_delivery_days=max_delivery_days,
        max_concurrency=max_concurrency,
        staleness_threshold_days=staleness_threshold_days,
        products=scoped_products,
        stale_external_ids=staleness.stale_external_ids,
        estimate=estimate,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/scans/test_orchestration.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/scans/orchestration.py backend/tests/scans/test_orchestration.py
git commit -m "Add create_scan orchestration tying CSV, sampling, staleness, and estimate together"
```

---

## Task 9: Async job engine

**Files:**
- Create: `backend/app/scans/engine.py`
- Test: `backend/tests/scans/test_engine.py`

**Interfaces:**
- Consumes: `get_offer_cached` from `app.providers.lookup` (Task 1's new-contract version),
  `ProviderUnavailable` from `app.providers.base`, `ScanStore` from Task 7, `PriceCache` from
  `app.cache.sqlite_cache`, `PriceProvider` from `app.providers.base`.
- Produces: `async def run_scan(scan_id: str, store: ScanStore, cache: PriceCache, provider:
  PriceProvider, market: str, max_delivery_days: int, max_concurrency: int) -> None`. Used by
  Task 10's `api.py` (dispatched as a background task from `POST /scans/{id}/start`), and is
  the function a process restart calls again for the same `scan_id` to resume.

Per-product behavior: on a genuine result (an `OfferResult` or `None` — both are legitimate
outcomes `get_offer_cached` can now return without raising), mark the product `done` with
that offer. On `ProviderUnavailable`, leave the product's status untouched (still `pending`)
so a later call to `run_scan` for this `scan_id` retries it — this is the mechanism that makes
resumability actually work for transient failures, not just process crashes. If a product was
flagged `was_stale=True` in the store, it is skipped entirely (not looked up again) unless the
caller already invalidated its cache entry before calling `run_scan` (that invalidation step
belongs to Task 10's `POST /scans/{id}/start`, using Task 2's `PriceCache.invalidate`, when the
user chose to force a refresh — `run_scan` itself doesn't need to know about that choice, it
just processes whatever is `pending`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/scans/test_engine.py
import asyncio
from decimal import Decimal

import pytest

from app.cache.sqlite_cache import PriceCache
from app.models.product import Product
from app.providers.base import OfferResult, ProviderUnavailable
from app.scans.engine import run_scan
from app.scans.estimate import estimate_cost
from app.scans.models import ProductStatus, ScanStatus
from app.scans.store import ScanStore


def _make_product(**overrides) -> Product:
    defaults = dict(
        tenant_id="t1", source="csv", external_id="1", variant_id=None,
        name="Test Product", ean="5901234123457",
        wholesale_price=Decimal("60.00"), currency="PLN", category="Test",
    )
    defaults.update(overrides)
    return Product(**defaults)


def _make_offer(**overrides) -> OfferResult:
    defaults = dict(
        price=Decimal("89.99"), currency="PLN", seller="Example Shop",
        source_url="https://example.com/product", delivery_days=2,
        confidence=0.85, citations=("https://example.com/product",),
        raw_response="{}",
    )
    defaults.update(overrides)
    return OfferResult(**defaults)


class _ScriptedProvider:
    """Returns/raises the next item in `script` for each product's EAN, in
    call order. Tracks max concurrent in-flight calls to verify the semaphore."""

    name = "perplexity"

    def __init__(self, script: dict[str, object]):
        self._script = script
        self.call_count = 0
        self._in_flight = 0
        self.max_in_flight = 0

    def find_cheapest(self, product, market, max_delivery_days):
        self._in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            self.call_count += 1
            outcome = self._script[product.ean]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        finally:
            self._in_flight -= 1


def _make_store_with_products(tmp_path, products, *, max_concurrency=5):
    store = ScanStore(tmp_path / "app.sqlite3")
    estimate = estimate_cost(cache_misses=len(products), stale_count=0, max_concurrency=max_concurrency)
    scan_id = store.create_scan(
        scope_type="full", sample_per_category=None, market="PL", max_delivery_days=5,
        max_concurrency=max_concurrency, staleness_threshold_days=14,
        products=products, stale_external_ids=(), estimate=estimate,
    )
    return store, scan_id


def test_run_scan_marks_all_products_done_and_finalizes(tmp_path):
    products = [_make_product(external_id="1", ean="5901234123457")]
    store, scan_id = _make_store_with_products(tmp_path, products)
    cache = PriceCache(tmp_path / "app.sqlite3")
    provider = _ScriptedProvider({"5901234123457": _make_offer()})

    asyncio.run(run_scan(scan_id, store, cache, provider, "PL", 5, max_concurrency=5))

    assert store.list_pending(scan_id) == []
    assert store.get_scan(scan_id).status == ScanStatus.DONE
    assert store.get_scan(scan_id).completed_products == 1
    store.close()
    cache.close()


def test_run_scan_leaves_transiently_failed_products_pending_and_marks_scan_failed(tmp_path):
    products = [
        _make_product(external_id="1", ean="5901234123457"),
        _make_product(external_id="2", ean="5900000000009"),
    ]
    store, scan_id = _make_store_with_products(tmp_path, products)
    cache = PriceCache(tmp_path / "app.sqlite3")
    provider = _ScriptedProvider({
        "5901234123457": _make_offer(),
        "5900000000009": ProviderUnavailable("simulated transient failure"),
    })

    asyncio.run(run_scan(scan_id, store, cache, provider, "PL", 5, max_concurrency=5))

    pending = store.list_pending(scan_id)
    assert len(pending) == 1
    assert pending[0].product.external_id == "2"
    assert store.get_scan(scan_id).status == ScanStatus.FAILED
    store.close()
    cache.close()


def test_run_scan_can_be_called_again_to_resume_remaining_pending(tmp_path):
    products = [
        _make_product(external_id="1", ean="5901234123457"),
        _make_product(external_id="2", ean="5900000000009"),
    ]
    store, scan_id = _make_store_with_products(tmp_path, products)
    cache = PriceCache(tmp_path / "app.sqlite3")
    failing_provider = _ScriptedProvider({
        "5901234123457": _make_offer(),
        "5900000000009": ProviderUnavailable("simulated transient failure"),
    })
    asyncio.run(run_scan(scan_id, store, cache, failing_provider, "PL", 5, max_concurrency=5))
    assert len(store.list_pending(scan_id)) == 1

    recovered_provider = _ScriptedProvider({"5900000000009": _make_offer(price=Decimal("5.00"))})
    asyncio.run(run_scan(scan_id, store, cache, recovered_provider, "PL", 5, max_concurrency=5))

    assert store.list_pending(scan_id) == []
    assert store.get_scan(scan_id).status == ScanStatus.DONE
    assert recovered_provider.call_count == 1  # only the still-pending product was retried
    store.close()
    cache.close()


def test_run_scan_never_exceeds_max_concurrency(tmp_path):
    products = [
        _make_product(external_id=str(i), ean=f"590000000{i:04d}")
        for i in range(20)
    ]
    # Fix up EANs to be valid-looking 13-digit strings the cache can key on;
    # correctness of the EAN checksum doesn't matter here, only uniqueness.
    products = [
        _make_product(external_id=str(i), ean=f"{5900000000000 + i}")
        for i in range(20)
    ]
    store, scan_id = _make_store_with_products(tmp_path, products, max_concurrency=3)
    cache = PriceCache(tmp_path / "app.sqlite3")
    script = {p.ean: _make_offer() for p in products}
    provider = _ScriptedProvider(script)

    asyncio.run(run_scan(scan_id, store, cache, provider, "PL", 5, max_concurrency=3))

    assert provider.max_in_flight <= 3
    assert store.get_scan(scan_id).status == ScanStatus.DONE
    store.close()
    cache.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/scans/test_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.scans.engine'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/scans/engine.py
from __future__ import annotations

import asyncio

from app.cache.sqlite_cache import PriceCache
from app.providers.base import PriceProvider, ProviderUnavailable
from app.providers.lookup import get_offer_cached
from app.scans.store import ScanStore


async def run_scan(
    scan_id: str,
    store: ScanStore,
    cache: PriceCache,
    provider: PriceProvider,
    market: str,
    max_delivery_days: int,
    max_concurrency: int,
) -> None:
    store.start_scan(scan_id)
    pending = store.list_pending(scan_id)
    semaphore = asyncio.Semaphore(max_concurrency)

    async def process(record) -> None:
        async with semaphore:
            try:
                offer = await asyncio.to_thread(
                    get_offer_cached, record.product, market, max_delivery_days, cache, provider
                )
            except ProviderUnavailable:
                # Leave it pending — a later run_scan() call for this scan_id
                # (process restart, or a retry) will pick it up again.
                return
            store.mark_done(record.id, offer)

    await asyncio.gather(*(process(record) for record in pending))
    store.finalize_scan(scan_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/scans/test_engine.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/scans/engine.py backend/tests/scans/test_engine.py
git commit -m "Add async concurrency-limited job engine with crash-resilient resumability"
```

---

## Task 10: FastAPI routes (REST + SSE)

**Files:**
- Create: `backend/app/scans/api.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/scans/test_api.py`

**Interfaces:**
- Consumes: `create_scan` from Task 8, `run_scan` from Task 9, `ScanStore`/`PriceCache`
  instances, `PriceCache.invalidate` from Task 2.
- Produces: a FastAPI `APIRouter` (importable as `app.scans.api.router`) with:
  - `POST /scans` — multipart form: `file` (the CSV), `scope_type` (`"full"`/`"sample"`),
    `sample_per_category` (optional int), `market` (default `"PL"`), `max_delivery_days`
    (default `5`), `max_concurrency` (default `5`), `staleness_threshold_days` (default `14`).
    Returns `{"scan_id": ..., "status": ..., "total_products": ..., "estimate": {...},
    "overlapping_count": ...}`.
  - `POST /scans/{scan_id}/start` — JSON body: `{"force_refresh_stale": bool}`. If true,
    invalidates the cache entry for every product on this scan flagged `was_stale`, then
    dispatches `run_scan` as a `BackgroundTasks` job. Returns `{"status": "running"}` or 404 if
    the scan doesn't exist.
  - `GET /scans/{scan_id}` — returns the current `Scan` as JSON, or 404.
  - `GET /scans/{scan_id}/events` — SSE stream (`text/event-stream`) that polls
    `store.get_scan(scan_id)` every 0.3s and yields a `data: {...}\n\n` event each tick until
    status is `done` or `failed`, then sends a final event and closes.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/scans/test_api.py
import io
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.cache.sqlite_cache import PriceCache
from app.providers.base import OfferResult
from app.scans.api import get_cache, get_provider, get_store, router
from app.scans.store import ScanStore

CSV_BYTES = (
    "nazwa;cena;ean;kategoria\n"
    "Produkt A;10,00;5901234123457;Elektronika\n"
).encode("utf-8")


class _FakeProvider:
    name = "perplexity"

    def find_cheapest(self, product, market, max_delivery_days):
        return OfferResult(
            price=Decimal("15.00"), currency="PLN",
            seller="Shop", source_url="https://example.com/x", delivery_days=2,
            confidence=0.9, citations=(), raw_response="{}",
        )


def _make_app(tmp_path):
    app = FastAPI()
    app.include_router(router)
    store = ScanStore(tmp_path / "app.sqlite3")
    cache = PriceCache(tmp_path / "app.sqlite3")
    provider = _FakeProvider()
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_cache] = lambda: cache
    app.dependency_overrides[get_provider] = lambda: provider
    return app, store, cache


def test_post_scans_creates_an_estimated_scan_without_starting_it(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "full"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "estimated"
    assert body["total_products"] == 1
    assert "estimate" in body
    assert store.get_scan(body["scan_id"]).status.value == "estimated"


def test_get_scans_returns_404_for_unknown_id(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.get("/scans/does-not-exist")

    assert response.status_code == 404


def test_start_scan_runs_it_to_completion(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)
    scan_id = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "full"},
    ).json()["scan_id"]

    response = client.post(f"/scans/{scan_id}/start", json={"force_refresh_stale": False})

    assert response.status_code == 200
    final = client.get(f"/scans/{scan_id}").json()
    assert final["status"] == "done"
    assert final["completed_products"] == 1


def test_start_scan_returns_404_for_unknown_id(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post("/scans/does-not-exist/start", json={"force_refresh_stale": False})

    assert response.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/scans/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.scans.api'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/scans/api.py
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.cache.sqlite_cache import PriceCache
from app.providers.base import PriceProvider
from app.providers.perplexity import PerplexityProvider
from app.scans.engine import run_scan
from app.scans.orchestration import create_scan
from app.scans.store import ScanStore

router = APIRouter()

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "app.sqlite3"
_shared_store: ScanStore | None = None
_shared_cache: PriceCache | None = None
_shared_provider: PriceProvider | None = None


def get_store() -> ScanStore:
    global _shared_store
    if _shared_store is None:
        DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _shared_store = ScanStore(DEFAULT_DB_PATH)
    return _shared_store


def get_cache() -> PriceCache:
    global _shared_cache
    if _shared_cache is None:
        DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _shared_cache = PriceCache(DEFAULT_DB_PATH)
    return _shared_cache


def get_provider() -> PriceProvider:
    global _shared_provider
    if _shared_provider is None:
        import os
        _shared_provider = PerplexityProvider(api_key=os.environ["PERPLEXITY_API_KEY"])
    return _shared_provider


def _estimate_to_dict(estimate) -> dict:
    return {
        "queries_without_refresh": estimate.queries_without_refresh,
        "queries_with_refresh": estimate.queries_with_refresh,
        "cost_usd_without_refresh": str(estimate.cost_usd_without_refresh),
        "cost_usd_with_refresh": str(estimate.cost_usd_with_refresh),
        "seconds_without_refresh": estimate.seconds_without_refresh,
        "seconds_with_refresh": estimate.seconds_with_refresh,
    }


def _scan_to_dict(scan) -> dict:
    return {
        "scan_id": scan.id,
        "status": scan.status.value,
        "scope_type": scan.scope_type,
        "total_products": scan.total_products,
        "completed_products": scan.completed_products,
        "estimate": _estimate_to_dict(scan.estimate),
    }


def _sample_seed_from_csv(csv_bytes: bytes) -> int:
    # Deterministic per-upload seed derived from the file's actual content (not
    # just its length) so re-uploading the same file sample the same products;
    # not security-sensitive, just needs to be stable and content-dependent.
    return int(hashlib.sha256(csv_bytes).hexdigest()[:8], 16)


@router.post("/scans")
async def post_scans(
    file: UploadFile,
    scope_type: str = Form(...),
    sample_per_category: int | None = Form(None),
    market: str = Form("PL"),
    max_delivery_days: int = Form(5),
    max_concurrency: int = Form(5),
    staleness_threshold_days: int = Form(14),
    store: ScanStore = Depends(get_store),
    cache: PriceCache = Depends(get_cache),
    provider: PriceProvider = Depends(get_provider),
):
    csv_bytes = await file.read()
    scan_id = create_scan(
        csv_bytes=csv_bytes, tenant_id="default", scope_type=scope_type,
        sample_per_category=sample_per_category, sample_seed=_sample_seed_from_csv(csv_bytes),
        market=market, max_delivery_days=max_delivery_days, max_concurrency=max_concurrency,
        staleness_threshold_days=staleness_threshold_days,
        store=store, cache=cache, provider_name=provider.name,
    )
    scan = store.get_scan(scan_id)
    return _scan_to_dict(scan)


class StartScanRequest(BaseModel):
    force_refresh_stale: bool


@router.post("/scans/{scan_id}/start")
async def start_scan(
    scan_id: str,
    body: StartScanRequest,
    background_tasks: BackgroundTasks,
    store: ScanStore = Depends(get_store),
    cache: PriceCache = Depends(get_cache),
    provider: PriceProvider = Depends(get_provider),
):
    scan = store.get_scan(scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="scan not found")

    if body.force_refresh_stale:
        for record in store.list_pending(scan_id):
            if record.was_stale and record.product.ean:
                cache.invalidate(record.product.ean, scan.market, provider.name, scan.max_delivery_days)

    background_tasks.add_task(
        run_scan, scan_id, store, cache, provider, scan.market, scan.max_delivery_days, scan.max_concurrency
    )
    return {"status": "running"}


@router.get("/scans/{scan_id}")
async def get_scan_status(scan_id: str, store: ScanStore = Depends(get_store)):
    scan = store.get_scan(scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="scan not found")
    return _scan_to_dict(scan)


@router.get("/scans/{scan_id}/events")
async def stream_scan_events(scan_id: str, store: ScanStore = Depends(get_store)):
    scan = store.get_scan(scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="scan not found")

    async def event_generator():
        while True:
            scan = store.get_scan(scan_id)
            yield f"data: {json.dumps(_scan_to_dict(scan))}\n\n"
            if scan.status.value in ("done", "failed"):
                break
            await asyncio.sleep(0.3)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

```python
# backend/app/main.py — add these two lines
from app.scans.api import router as scans_router
# ... after `app = FastAPI(title="IS_IT_WORTH_IT")`:
app.include_router(scans_router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/scans/test_api.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && .venv/bin/pytest -q`
Expected: all tests pass, including every earlier Phase 3/4 test file, plus the 2 opt-in
live-Perplexity tests still skipping cleanly without `PERPLEXITY_API_KEY`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/scans/api.py backend/app/main.py backend/tests/scans/test_api.py
git commit -m "Add REST+SSE API for creating, starting, and observing scans"
```

---

## Self-Review Notes

- **Spec coverage:** persistence (`products`/`scans` tables) — Task 7. Scope resolution
  (full/sample + water-filling) — Task 4, wired in Task 8. Cost/time estimate before start —
  Task 5, wired in Task 8, exposed via `POST /scans` in Task 10. Async/concurrency-limited/
  resumable engine — Task 9. Staleness detection — Task 6, wired in Task 8, exposed via
  `POST /scans` and consumed by `POST /scans/{id}/start`'s `force_refresh_stale` in Task 10.
  Two-step start (never surprise the user with cost) — enforced by `POST /scans` never calling
  `run_scan`, only `POST /scans/{id}/start` does (Task 10). SSE streaming — Task 10.
  Deliberately not covered (Phase 5 per spec): the actual UI, the column-mapping correction
  screen.
- **Placeholder scan:** none — every step has real code, including the note in Task 10 Step 3
  about double-checking the `sample_seed` expression, which is a correctness caution about
  exact code already given, not an unwritten placeholder.
- **Type consistency:** `Scan`/`ScanProductRecord`/`CostEstimate`/`StalenessReport` (Task 3)
  are used with identical field names across `store.py` (Task 7), `estimate.py` (Task 5),
  `staleness.py` (Task 6), `orchestration.py` (Task 8), `engine.py` (Task 9), and `api.py`
  (Task 10). `ScanStore.create_scan`'s keyword arguments match exactly between Task 7's
  definition and Task 8's call site. `get_offer_cached`'s new (Task 1) contract — returns
  `OfferResult | None`, raises `ProviderUnavailable` — is what Task 9's `engine.py` relies on
  to distinguish "done" from "leave pending."

## Next steps after this plan

Phase 5 (frontend): the actual screens (Upload → Mapowanie kolumn → Zakres + estymacja kosztu
→ Przebieg → Raport), consuming this phase's REST+SSE API. Also the two deferred provider
decisions from the Phase 4 design spec: revisit open-web SERP once a real scan on the user's
full catalog gives actual `found=false`/low-confidence percentages (not estimates), and Allegro
remains an open "someday" item with no fixed date.
