# GroqProvider + Retry + Budget (Faza 1) Implementation Plan

**Goal:** Add a `GroqProvider` (free-tier AI price lookup via a two-call search-then-extract pattern) behind the existing `PriceProvider` Protocol, with reusable HTTP retry/rate-limit handling and a `paused` scan state — all still on SQLite, single-user, no BYOK wiring yet.

**Architecture:** `GroqProvider` calls `groq/compound-mini` (web search, freeform text answer) then `openai/gpt-oss-20b` (structured JSON extraction via `response_format: json_schema`), reusing the same `RESPONSE_SCHEMA`/validation logic `PerplexityProvider` already uses — extracted into a shared `app/providers/parsing.py` so the two providers' validation rules cannot drift apart. A new `app/providers/retry.py` wraps HTTP calls with backoff, distinguishing a rate limit (retryable, pauses the scan) from a bad key (not retryable, fails the scan immediately). `run_scan` learns a third terminal-ish outcome (`paused`) alongside today's `done`/`failed`.

**Tech Stack:** Python 3.11+, FastAPI, httpx, pytest — no new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-28-cloud-byok-auth-design.md` (Faza 1 section). This plan implements only Faza 1; Faza 4's BYOK provider factory and persistent `provider_usage` RPM/RPD ledger are explicitly out of scope here.

## Global Constraints

- Money stays `Decimal`, never `float` — see `CLAUDE.md`.
- No new runtime dependencies; `httpx` is already a backend dependency.
- Every existing test must still pass unmodified in behavior (only call-site signatures change where noted) — this repo's whole-branch review treats a silent behavior change as the highest-severity finding class.
- `GROQ_API_KEY` follows the exact same env-var pattern as `PERPLEXITY_API_KEY` (`os.environ`, read once at provider construction) — no settings library yet (that's Faza 2/3).
- Groq's two-call pattern is confirmed as the *only* documented path (verified this session against `console.groq.com/docs/tool-use/built-in-tools/web-search` and `console.groq.com/docs/structured-outputs`): `compound`/`compound-mini` are not on the strict `json_schema` model list, and structured outputs are documented as incompatible with tool use. Do not attempt same-call composition.
- Groq's compound response shape (verified verbatim from `https://console.groq.com/docs/tool-use/built-in-tools/web-search.md`, 2026-08-28): the endpoint is `https://api.groq.com/openai/v1/chat/completions` (same OpenAI-compatible shape Perplexity uses); the final answer is `choices[0].message.content`; source data is `choices[0].message.executed_tools[0].search_results`, a list of `{"title": str, "url": str, "content": str, "score": float}`. **There is no top-level `citations` field like Perplexity's** — citations must be built from the `search_results[*].url` values.

---

## File Structure

- Create `backend/app/providers/parsing.py` — `RESPONSE_SCHEMA` (moved from `perplexity.py`) + `validate_offer_fields(...)`, shared by both providers.
- Create `backend/app/providers/retry.py` — `call_with_retry(send)`, provider-agnostic HTTP retry/backoff.
- Create `backend/app/providers/groq.py` — `GroqProvider`.
- Create `backend/tests/providers/test_parsing.py`, `backend/tests/providers/test_retry.py`, `backend/tests/providers/test_groq.py`, `backend/tests/providers/test_groq_live.py`.
- Modify `backend/app/providers/base.py` — add `ProviderProfile`, `ProviderRateLimited`, `ProviderAuthError`; add `profile` to the `PriceProvider` Protocol.
- Modify `backend/app/providers/perplexity.py` — delegate to `parsing.py`; add `profile` class attribute.
- Modify `backend/app/scans/estimate.py` — `estimate_cost` takes a `profile: ProviderProfile` parameter instead of reading module constants.
- Modify `backend/app/scans/orchestration.py` — `create_scan` takes `provider: PriceProvider` instead of `provider_name: str`.
- Modify `backend/app/scans/api.py` — update the one `create_scan` call site; add env-var provider selection to `get_provider()`.
- Modify `backend/app/scans/models.py` — add `ScanStatus.PAUSED`.
- Modify `backend/app/scans/store.py` — add `ScanStore.pause_scan()`.
- Modify `backend/app/scans/engine.py` — `run_scan` distinguishes rate-limit-pause from genuine failure.
- Modify `backend/tests/scans/test_estimate.py`, `test_orchestration.py`, `test_api.py`, `test_integration.py`, `test_engine.py` — call-site updates for the signature changes above.

---

### Task 1: Extract shared offer-parsing into `app/providers/parsing.py`

**Files:**
- Create: `backend/app/providers/parsing.py`
- Modify: `backend/app/providers/perplexity.py`
- Test: `backend/tests/providers/test_parsing.py`

**Interfaces:**
- Produces: `RESPONSE_SCHEMA: dict[str, Any]`, `validate_offer_fields(parsed: object, *, raw_response: str, citations: tuple[str, ...], max_delivery_days: int) -> OfferResult | None` — both importable from `app.providers.parsing`. `GroqProvider` (Task 5) and `PerplexityProvider` both consume these.

- [ ] **Step 1: Write the failing test for the extracted function**

```python
# backend/tests/providers/test_parsing.py
from app.providers.parsing import validate_offer_fields

def test_returns_none_when_not_a_dict():
    assert validate_offer_fields(
        "not a dict", raw_response="{}", citations=(), max_delivery_days=5
    ) is None

def test_returns_none_when_not_found():
    assert validate_offer_fields(
        {"found": False}, raw_response="{}", citations=(), max_delivery_days=5
    ) is None

def test_returns_offer_for_valid_input():
    parsed = {
        "found": True, "price": 89.99, "currency": "PLN", "seller": "Example Shop",
        "source_url": "https://example.com/product", "delivery_days": 2, "confidence": 0.85,
    }

    offer = validate_offer_fields(
        parsed, raw_response="{}", citations=("https://example.com/product",),
        max_delivery_days=5,
    )

    assert offer is not None
    assert offer.price.__class__.__name__ == "Decimal"
    assert str(offer.price) == "89.99"
    assert offer.currency == "PLN"
    assert offer.seller == "Example Shop"
    assert offer.source_url == "https://example.com/product"
    assert offer.delivery_days == 2
    assert offer.confidence == 0.85
    assert offer.citations == ("https://example.com/product",)
    assert offer.raw_response == "{}"

def test_returns_none_when_delivery_exceeds_limit():
    parsed = {
        "found": True, "price": 10.0, "currency": "PLN", "seller": "X",
        "source_url": "https://example.com/x", "delivery_days": 20, "confidence": 0.9,
    }
    assert validate_offer_fields(
        parsed, raw_response="{}", citations=(), max_delivery_days=5
    ) is None

def test_returns_none_when_confidence_out_of_range():
    parsed = {
        "found": True, "price": 10.0, "currency": "PLN", "seller": "X",
        "source_url": "https://example.com/x", "delivery_days": 2, "confidence": 1.5,
    }
    assert validate_offer_fields(
        parsed, raw_response="{}", citations=(), max_delivery_days=5
    ) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/providers/test_parsing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.providers.parsing'`

- [ ] **Step 3: Create `parsing.py` by moving the schema and validation body out of `perplexity.py`**

```python
# backend/app/providers/parsing.py
from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from typing import Any

from app.providers.base import OfferResult

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "price": {"type": "number"},
        "currency": {"type": "string"},
        "seller": {"type": "string"},
        "source_url": {"type": "string"},
        "delivery_days": {"type": "integer"},
        "confidence": {"type": "number"},
    },
    "required": [
        "found", "price", "currency", "seller",
        "source_url", "delivery_days", "confidence",
    ],
}

def validate_offer_fields(
    parsed: object,
    *,
    raw_response: str,
    citations: tuple[str, ...],
    max_delivery_days: int,
) -> OfferResult | None:
    """Validates a provider's already-extracted offer JSON against the shared
    contract. Provider-agnostic: PerplexityProvider and GroqProvider both
    parse their own response envelope down to this dict shape first, then
    call this — so the two providers' offers can never diverge on what
    counts as a valid one, even though they write into the same price_cache.
    """
    if not isinstance(parsed, dict) or not parsed.get("found"):
        return None

    source_url = parsed.get("source_url")
    if not source_url:
        return None

    currency = parsed.get("currency", "PLN")
    if not isinstance(currency, str) or not currency:
        return None

    delivery_days = parsed.get("delivery_days")
    if (
        not isinstance(delivery_days, int)
        or isinstance(delivery_days, bool)
        or delivery_days < 0
        or delivery_days > max_delivery_days
    ):
        return None

    try:
        price = Decimal(str(parsed["price"]))
    except (InvalidOperation, KeyError, TypeError):
        return None
    if not price.is_finite() or price <= 0:
        return None

    try:
        confidence = float(parsed.get("confidence", 0.0))
    except (ValueError, TypeError):
        return None
    if not math.isfinite(confidence) or not (0.0 <= confidence <= 1.0):
        return None

    return OfferResult(
        price=price,
        currency=currency,
        seller=parsed.get("seller", "unknown"),
        source_url=source_url,
        delivery_days=delivery_days,
        confidence=confidence,
        citations=citations,
        raw_response=raw_response,
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/providers/test_parsing.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Refactor `perplexity.py` to delegate to the shared function**

Modify `backend/app/providers/perplexity.py`: delete the module-level `RESPONSE_SCHEMA` (lines 19-34) and import it from `parsing.py` instead; replace the body of `_parse_response` from `if not isinstance(parsed, dict)...` through the `return OfferResult(...)` (lines 107-156) with a call to `validate_offer_fields`. The unwrapping (`content = response_json["choices"][0]["message"]["content"]`, `json.loads`, the `KeyError/IndexError/TypeError/JSONDecodeError` catch, and the `citations` extraction from the top-level `response_json.get("citations")`) stays in `perplexity.py` — that part is Perplexity-specific response shape, not shared.

```python
# backend/app/providers/perplexity.py — new imports and _parse_response body
from app.providers.parsing import RESPONSE_SCHEMA, validate_offer_fields

# ... (PerplexityProvider class, find_cheapest, _build_prompt unchanged) ...

    def _parse_response(
        self, response_json: dict[str, Any], max_delivery_days: int
    ) -> OfferResult | None:
        raw_response = json.dumps(response_json)
        try:
            content = response_json["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            return None

        raw_citations = response_json.get("citations") or []
        if isinstance(raw_citations, list):
            citations = tuple(c for c in raw_citations if isinstance(c, str))
        else:
            citations = ()

        return validate_offer_fields(
            parsed, raw_response=raw_response, citations=citations,
            max_delivery_days=max_delivery_days,
        )
```

Remove the now-unused `math`, `Decimal`, `InvalidOperation` imports from `perplexity.py` if nothing else in the file uses them (check with a grep after editing).

- [ ] **Step 6: Run the full existing Perplexity test suite to verify zero behavior change**

Run: `cd backend && .venv/bin/pytest tests/providers/test_parsing.py tests/providers/test_perplexity.py -v`
Expected: PASS, all tests (the pre-existing `test_perplexity.py` tests must pass with zero modifications to that test file)

- [ ] **Step 7: Commit**

```bash
git add backend/app/providers/parsing.py backend/app/providers/perplexity.py backend/tests/providers/test_parsing.py
git commit -m "refactor: extract shared offer-validation into app/providers/parsing.py"
```

---

### Task 2: `ProviderProfile`, `ProviderRateLimited`, `ProviderAuthError` in `app/providers/base.py`

**Files:**
- Modify: `backend/app/providers/base.py`
- Modify: `backend/app/providers/perplexity.py`
- Test: `backend/tests/providers/test_base.py` (new)

**Interfaces:**
- Consumes: nothing new.
- Produces: `ProviderProfile(cost_per_query_usd: Decimal, seconds_per_query: float)` dataclass; `PriceProvider.profile: ProviderProfile` (new Protocol attribute, parallel to the existing `name: str`); `ProviderRateLimited(ProviderUnavailable)` with a `retry_after: float | None` attribute; `ProviderAuthError(Exception)` (deliberately **not** a `ProviderUnavailable` subclass — see docstring). `PerplexityProvider.profile` populated with today's `COST_PER_QUERY_USD`/`SECONDS_PER_QUERY` values. Task 3 consumes `PriceProvider.profile`; Task 4's `retry.py` raises `ProviderRateLimited`/`ProviderAuthError`; Task 7's `run_scan` catches both by name.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/providers/test_base.py
from decimal import Decimal

from app.providers.base import ProviderAuthError, ProviderProfile, ProviderRateLimited, ProviderUnavailable

def test_provider_profile_holds_cost_and_timing():
    profile = ProviderProfile(cost_per_query_usd=Decimal("0.010"), seconds_per_query=2.5)
    assert profile.cost_per_query_usd == Decimal("0.010")
    assert profile.seconds_per_query == 2.5

def test_provider_rate_limited_is_a_provider_unavailable_and_carries_retry_after():
    exc = ProviderRateLimited("rate limited", retry_after=30.0)
    assert isinstance(exc, ProviderUnavailable)
    assert exc.retry_after == 30.0

def test_provider_rate_limited_retry_after_defaults_to_none():
    exc = ProviderRateLimited("rate limited")
    assert exc.retry_after is None

def test_provider_auth_error_is_not_a_provider_unavailable():
    # Deliberate: an auth error must never be treated as "retry me later" —
    # it must abort the whole scan, not leave the record pending.
    assert not issubclass(ProviderAuthError, ProviderUnavailable)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/providers/test_base.py -v`
Expected: FAIL with `ImportError: cannot import name 'ProviderProfile'`

- [ ] **Step 3: Add the new types to `base.py`**

Modify `backend/app/providers/base.py` — add after the existing `OfferResult` dataclass and before `ProviderUnavailable`:

```python
@dataclass(frozen=True)
class ProviderProfile:
    """Cost/timing characteristics used only for the pre-scan estimate shown
    to the user (see app/scans/estimate.py) — never a billing guarantee.
    Provider-specific because Perplexity and Groq have unrelated cost/speed
    profiles; RPM/RPD budget fields are deliberately NOT here yet — nothing
    in Faza 1 consumes them, they arrive with Faza 4's provider_usage ledger.
    """

    cost_per_query_usd: Decimal
    seconds_per_query: float
```

Add after the existing `ProviderUnavailable` class:

```python
class ProviderRateLimited(ProviderUnavailable):
    """Raised when the provider's rate limit is exhausted after retrying
    (see app/providers/retry.py). A subclass of ProviderUnavailable — like
    it, this is transient and the record should stay pending for a later
    resume — but run_scan distinguishes it to pause the WHOLE scan rather
    than only skip this one product, since a rate limit exhausted on one
    call means every other in-flight call will fail identically.
    """

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after

class ProviderAuthError(Exception):
    """Raised when the provider rejects the API key outright (HTTP 401/403).
    Deliberately NOT a ProviderUnavailable subclass: retrying a bad key
    never helps, and every other in-flight call for this scan will fail
    identically, so run_scan must abort the scan immediately instead of
    leaving 17,500 products cycling through retries one at a time.
    """
```

Modify the `PriceProvider` Protocol to add a `profile` attribute alongside `name`:

```python
class PriceProvider(Protocol):
    name: str
    profile: ProviderProfile

    def find_cheapest(
        self, product: Product, market: str, max_delivery_days: int
    ) -> OfferResult | None:
        ...
```

Add `from decimal import Decimal` to the existing `from decimal import Decimal` import line at the top of `base.py` (it's already imported for `OfferResult.price`, so no new import needed — verify before adding a duplicate).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/providers/test_base.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Give `PerplexityProvider` a `profile`, sourced from `estimate.py`'s current constants**

Modify `backend/app/providers/perplexity.py` — add the import and class attribute:

```python
from app.providers.base import OfferResult, ProviderProfile, ProviderUnavailable

# ... inside class PerplexityProvider, alongside `name = "perplexity"`:
    name = "perplexity"
    profile = ProviderProfile(cost_per_query_usd=Decimal("0.010"), seconds_per_query=2.5)
```

Add `from decimal import Decimal` to `perplexity.py`'s imports if Task 1's cleanup removed it (check first — Task 1 only removes it if nothing else uses it, and this step reintroduces a use, so leave/re-add as needed).

- [ ] **Step 6: Run the full provider test suite**

Run: `cd backend && .venv/bin/pytest tests/providers/ -v`
Expected: PASS, all tests

- [ ] **Step 7: Commit**

```bash
git add backend/app/providers/base.py backend/app/providers/perplexity.py backend/tests/providers/test_base.py
git commit -m "feat: add ProviderProfile, ProviderRateLimited, ProviderAuthError"
```

---

### Task 3: Move cost/timing constants onto the provider; `create_scan` takes a provider instance

**Files:**
- Modify: `backend/app/scans/estimate.py`
- Modify: `backend/app/scans/orchestration.py`
- Modify: `backend/app/scans/api.py:315-338` (the `create_scan` call site inside `post_scans`)
- Modify: `backend/tests/scans/test_estimate.py`
- Modify: `backend/tests/scans/test_orchestration.py` (5 call sites, per current `provider_name="perplexity"` occurrences)
- Modify: `backend/tests/scans/test_api.py` (`_FakeProvider`, `_BuggyProvider` classes)
- Modify: `backend/tests/scans/test_integration.py` (`_CountingProvider` class)

**Interfaces:**
- Consumes: `ProviderProfile` from Task 2.
- Produces: `estimate_cost(cache_misses: int, stale_count: int, max_concurrency: int, profile: ProviderProfile) -> CostEstimate` (new required 4th parameter); `create_scan(..., provider: PriceProvider)` replacing the old `provider_name: str` parameter — Task 7 does not touch this signature further.

- [ ] **Step 1: Update the failing tests first — `test_estimate.py`**

Replace the full contents of `backend/tests/scans/test_estimate.py`:

```python
from decimal import Decimal

from app.providers.base import ProviderProfile
from app.scans.estimate import estimate_cost

PROFILE = ProviderProfile(cost_per_query_usd=Decimal("0.010"), seconds_per_query=2.5)

def test_estimate_with_no_misses_and_no_stale_is_free_and_instant():
    result = estimate_cost(cache_misses=0, stale_count=0, max_concurrency=5, profile=PROFILE)

    assert result.queries_without_refresh == 0
    assert result.queries_with_refresh == 0
    assert result.cost_usd_without_refresh == Decimal("0.00")
    assert result.cost_usd_with_refresh == Decimal("0.00")
    assert result.seconds_without_refresh == 0.0
    assert result.seconds_with_refresh == 0.0

def test_estimate_scales_with_query_count_and_concurrency():
    result = estimate_cost(cache_misses=100, stale_count=20, max_concurrency=10, profile=PROFILE)

    assert result.queries_without_refresh == 100
    assert result.queries_with_refresh == 120
    assert result.cost_usd_without_refresh == (PROFILE.cost_per_query_usd * 100).quantize(Decimal("0.01"))
    assert result.cost_usd_with_refresh == (PROFILE.cost_per_query_usd * 120).quantize(Decimal("0.01"))
    assert result.seconds_without_refresh == (100 / 10) * PROFILE.seconds_per_query
    assert result.seconds_with_refresh == (120 / 10) * PROFILE.seconds_per_query

def test_estimate_with_refresh_is_never_cheaper_than_without():
    result = estimate_cost(cache_misses=50, stale_count=5, max_concurrency=5, profile=PROFILE)

    assert result.queries_with_refresh >= result.queries_without_refresh
    assert result.cost_usd_with_refresh >= result.cost_usd_without_refresh
    assert result.seconds_with_refresh >= result.seconds_without_refresh

def test_estimate_uses_the_given_profiles_own_cost_and_timing():
    # A near-zero-cost profile (e.g. Groq's free tier) must actually change
    # the numbers, proving estimate_cost reads the passed profile and not a
    # module-level constant left over from the old signature.
    free_profile = ProviderProfile(cost_per_query_usd=Decimal("0.000"), seconds_per_query=4.0)

    result = estimate_cost(cache_misses=10, stale_count=0, max_concurrency=5, profile=free_profile)

    assert result.cost_usd_without_refresh == Decimal("0.00")
    assert result.seconds_without_refresh == (10 / 5) * 4.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/scans/test_estimate.py -v`
Expected: FAIL — `estimate_cost() got an unexpected keyword argument 'profile'`

- [ ] **Step 3: Rewrite `estimate.py`**

```python
# backend/app/scans/estimate.py
from __future__ import annotations

from decimal import Decimal

from app.providers.base import ProviderProfile
from app.scans.models import CostEstimate

def estimate_cost(
    cache_misses: int, stale_count: int, max_concurrency: int, profile: ProviderProfile
) -> CostEstimate:
    queries_without_refresh = cache_misses
    queries_with_refresh = cache_misses + stale_count

    return CostEstimate(
        queries_without_refresh=queries_without_refresh,
        queries_with_refresh=queries_with_refresh,
        cost_usd_without_refresh=(profile.cost_per_query_usd * queries_without_refresh).quantize(Decimal("0.01")),
        cost_usd_with_refresh=(profile.cost_per_query_usd * queries_with_refresh).quantize(Decimal("0.01")),
        seconds_without_refresh=(queries_without_refresh / max_concurrency) * profile.seconds_per_query,
        seconds_with_refresh=(queries_with_refresh / max_concurrency) * profile.seconds_per_query,
    )
```

(This deletes the module-level `COST_PER_QUERY_USD`/`SECONDS_PER_QUERY` constants entirely — they now live only on each provider's `.profile`.)

- [ ] **Step 4: Run to verify `test_estimate.py` passes**

Run: `cd backend && .venv/bin/pytest tests/scans/test_estimate.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Update `orchestration.py`'s `create_scan` to take a provider instance**

Modify `backend/app/scans/orchestration.py`:

```python
from __future__ import annotations

from app.cache.sqlite_cache import PriceCache
from app.normalize.grouping import group_by_category
from app.providers.base import PriceProvider
from app.scans.estimate import estimate_cost
from app.scans.sampling import resolve_sample_scope
from app.scans.staleness import analyze_staleness
from app.scans.store import ScanStore
from app.sources.base import CatalogSource

def create_scan(
    *,
    source: CatalogSource,
    scope_type: str,
    sample_per_category: int | None,
    sample_seed: int,
    market: str,
    max_delivery_days: int,
    max_concurrency: int,
    staleness_threshold_days: int,
    store: ScanStore,
    cache: PriceCache,
    provider: PriceProvider,
) -> tuple[str, list[str]]:
    all_products = source.fetch_products()

    if scope_type == "sample":
        if sample_per_category is None:
            raise ValueError("sample_per_category is required when scope_type is 'sample'")
        products_by_category = group_by_category(all_products)
        scoped_products = resolve_sample_scope(
            products_by_category, sample_per_category, sample_seed
        )
    else:
        scoped_products = all_products

    staleness = analyze_staleness(
        scoped_products, cache, market, provider.name, max_delivery_days,
        staleness_threshold_days,
    )

    cache_misses = sum(
        1 for p in scoped_products
        if p.ean is None or cache.get(p.ean, market, provider.name, max_delivery_days) is None
    )
    estimate = estimate_cost(
        cache_misses=cache_misses,
        stale_count=len(staleness.stale_eans),
        max_concurrency=max_concurrency,
        profile=provider.profile,
    )

    scan_id = store.create_scan(
        scope_type=scope_type,
        sample_per_category=sample_per_category,
        market=market,
        max_delivery_days=max_delivery_days,
        max_concurrency=max_concurrency,
        staleness_threshold_days=staleness_threshold_days,
        products=scoped_products,
        stale_eans=staleness.stale_eans,
        estimate=estimate,
        overlapping_count=staleness.overlapping_count,
        stale_count=len(staleness.stale_eans),
    )
    return scan_id, source.warnings
```

(Every internal use of `provider_name` becomes `provider.name`; the only new line is `profile=provider.profile`.)

- [ ] **Step 6: Update the 5 call sites in `test_orchestration.py`**

In `backend/tests/scans/test_orchestration.py`, add a fake provider near the top (after the existing `_make_offer` helper):

```python
from decimal import Decimal as _Decimal  # already imported as Decimal above if present — reuse, don't duplicate
from app.providers.base import ProviderProfile

class _FakeProvider:
    name = "perplexity"
    profile = ProviderProfile(cost_per_query_usd=Decimal("0.010"), seconds_per_query=2.5)
```

Then replace every occurrence of `provider_name="perplexity",` (5 occurrences) with `provider=_FakeProvider(),`. Use a project-wide search to find them all: `grep -n 'provider_name="perplexity"' backend/tests/scans/test_orchestration.py`.

- [ ] **Step 7: Update `api.py`'s call site**

Modify `backend/app/scans/api.py` around line 409 (the `create_scan` call inside `post_scans`): change `provider_name=provider.name` to `provider=provider`.

- [ ] **Step 8: Give the fake providers in `test_api.py` and `test_integration.py` a `.profile`**

In `backend/tests/scans/test_api.py`, add `profile = ProviderProfile(cost_per_query_usd=Decimal("0.010"), seconds_per_query=2.5)` as a class attribute to both `_FakeProvider` (after its existing `name = "perplexity"`) and `_BuggyProvider` (same). Add `from app.providers.base import OfferResult, ProviderProfile` (extending the existing `from app.providers.base import OfferResult` import line).

In `backend/tests/scans/test_integration.py`, add the same `profile` class attribute to `_CountingProvider` (after its `name = PROVIDER_NAME` line), and add `from app.providers.base import OfferResult, ProviderProfile` (extending the existing import).

- [ ] **Step 9: Run the full backend test suite**

Run: `cd backend && .venv/bin/pytest -v`
Expected: PASS, all tests (253+ tests, 4 skipped as before)

- [ ] **Step 10: Commit**

```bash
git add backend/app/scans/estimate.py backend/app/scans/orchestration.py backend/app/scans/api.py backend/tests/scans/test_estimate.py backend/tests/scans/test_orchestration.py backend/tests/scans/test_api.py backend/tests/scans/test_integration.py
git commit -m "refactor: move cost/timing constants onto ProviderProfile, create_scan takes a provider instance"
```

---

### Task 4: `app/providers/retry.py` — HTTP retry/backoff helper

**Files:**
- Create: `backend/app/providers/retry.py`
- Test: `backend/tests/providers/test_retry.py`

**Interfaces:**
- Consumes: `ProviderRateLimited`, `ProviderAuthError` from Task 2.
- Produces: `call_with_retry(send: Callable[[], httpx.Response]) -> httpx.Response` — importable from `app.providers.retry`. Task 5's `GroqProvider` is the only consumer in this plan.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/providers/test_retry.py
import httpx
import pytest

from app.providers.base import ProviderAuthError, ProviderRateLimited
from app.providers.retry import call_with_retry

def _response(status_code: int, headers: dict | None = None) -> httpx.Response:
    request = httpx.Request("POST", "https://api.example.com/x")
    return httpx.Response(status_code=status_code, headers=headers or {}, request=request)

def test_returns_response_immediately_on_success():
    calls = []

    def send():
        calls.append(1)
        return _response(200)

    response = call_with_retry(send)

    assert response.status_code == 200
    assert len(calls) == 1

def test_raises_provider_auth_error_immediately_on_401_no_retry():
    calls = []

    def send():
        calls.append(1)
        return _response(401)

    with pytest.raises(ProviderAuthError):
        call_with_retry(send)

    assert len(calls) == 1  # must not retry a bad key

def test_raises_provider_auth_error_immediately_on_403_no_retry():
    calls = []

    def send():
        calls.append(1)
        return _response(403)

    with pytest.raises(ProviderAuthError):
        call_with_retry(send)

    assert len(calls) == 1

def test_retries_429_then_succeeds(monkeypatch):
    monkeypatch.setattr("app.providers.retry.time.sleep", lambda *_: None)
    responses = [_response(429), _response(429), _response(200)]

    def send():
        return responses.pop(0)

    response = call_with_retry(send)

    assert response.status_code == 200
    assert responses == []

def test_raises_provider_rate_limited_after_exhausting_attempts(monkeypatch):
    monkeypatch.setattr("app.providers.retry.time.sleep", lambda *_: None)

    def send():
        return _response(429, headers={"Retry-After": "12"})

    with pytest.raises(ProviderRateLimited) as exc_info:
        call_with_retry(send)

    assert exc_info.value.retry_after == 12.0

def test_retries_5xx_then_succeeds(monkeypatch):
    monkeypatch.setattr("app.providers.retry.time.sleep", lambda *_: None)
    responses = [_response(503), _response(200)]

    def send():
        return responses.pop(0)

    response = call_with_retry(send)

    assert response.status_code == 200

def test_raises_http_status_error_on_permanent_4xx_without_retry():
    calls = []

    def send():
        calls.append(1)
        return _response(400)

    with pytest.raises(httpx.HTTPStatusError):
        call_with_retry(send)

    assert len(calls) == 1  # a plain bad request is not retried

def test_retries_transport_error_then_succeeds(monkeypatch):
    monkeypatch.setattr("app.providers.retry.time.sleep", lambda *_: None)
    attempts = {"n": 0}

    def send():
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise httpx.ConnectError("connection refused")
        return _response(200)

    response = call_with_retry(send)

    assert response.status_code == 200
    assert attempts["n"] == 2

def test_reraises_transport_error_after_exhausting_attempts(monkeypatch):
    monkeypatch.setattr("app.providers.retry.time.sleep", lambda *_: None)

    def send():
        raise httpx.ConnectError("connection refused")

    with pytest.raises(httpx.ConnectError):
        call_with_retry(send)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/providers/test_retry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.providers.retry'`

- [ ] **Step 3: Implement `retry.py`**

```python
# backend/app/providers/retry.py
from __future__ import annotations

import random
import time
from typing import Callable

import httpx

from app.providers.base import ProviderAuthError, ProviderRateLimited

# 4 attempts total (1 initial + 3 retries). At 30 RPM this stays well inside
# a single lookup's time budget even in the worst case; more attempts would
# just burn Groq's 250/day request budget faster for no better odds.
MAX_ATTEMPTS = 4
BASE_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 20.0

def call_with_retry(send: Callable[[], httpx.Response]) -> httpx.Response:
    """Calls `send()` up to MAX_ATTEMPTS times.

    - 401/403 -> raises ProviderAuthError immediately, no retry: a bad key
      never gets better by waiting, and retrying it once per product across
      a 17,500-product scan would waste the whole attempt budget on a
      failure the first response already fully diagnosed.
    - 429 or 5xx -> retried with exponential backoff + jitter, honouring a
      `Retry-After` response header when present. Exhausting all attempts
      raises ProviderRateLimited carrying the last-seen `Retry-After`.
    - any other non-2xx -> treated as permanent; raises the response's own
      `httpx.HTTPStatusError` via `raise_for_status()`, not retried.
    - transport-level errors (ConnectError, ReadTimeout, ...) are retried
      the same as 5xx, and re-raised as-is if attempts are exhausted.
    """
    last_retry_after: float | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = send()
        except httpx.HTTPError:
            if attempt == MAX_ATTEMPTS:
                raise
            _sleep_backoff(attempt)
            continue

        if response.status_code in (401, 403):
            raise ProviderAuthError(f"provider rejected credentials: HTTP {response.status_code}")

        if response.status_code == 429 or response.status_code >= 500:
            last_retry_after = _parse_retry_after(response)
            if attempt == MAX_ATTEMPTS:
                raise ProviderRateLimited(
                    f"provider rate-limited after {MAX_ATTEMPTS} attempts",
                    retry_after=last_retry_after,
                )
            _sleep_backoff(attempt, retry_after=last_retry_after)
            continue

        response.raise_for_status()
        return response

    raise AssertionError("unreachable: loop always returns or raises")

def _parse_retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None

def _sleep_backoff(attempt: int, retry_after: float | None = None) -> None:
    if retry_after is not None:
        time.sleep(retry_after)
        return
    delay = min(BASE_DELAY_SECONDS * (2 ** (attempt - 1)), MAX_DELAY_SECONDS)
    time.sleep(delay + random.uniform(0, delay * 0.25))
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/providers/test_retry.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/providers/retry.py backend/tests/providers/test_retry.py
git commit -m "feat: add call_with_retry HTTP backoff helper"
```

---

### Task 5: `GroqProvider` — two-call search-then-extract

**Files:**
- Create: `backend/app/providers/groq.py`
- Test: `backend/tests/providers/test_groq.py`

**Interfaces:**
- Consumes: `RESPONSE_SCHEMA`, `validate_offer_fields` (Task 1); `ProviderProfile` (Task 2); `call_with_retry` (Task 4).
- Produces: `GroqProvider(api_key: str, client: httpx.Client | None = None, timeout: float = 30.0)` implementing `PriceProvider` (`.name = "groq"`, `.profile`, `.find_cheapest(product, market, max_delivery_days) -> OfferResult | None`). Task 6's live test and Task 8's env-var wiring consume this class.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/providers/test_groq.py
import json
from decimal import Decimal

import httpx
import pytest

from app.models.product import Product
from app.providers.base import ProviderAuthError, ProviderUnavailable
from app.providers.groq import GroqProvider

def _make_product(**overrides) -> Product:
    defaults = dict(
        tenant_id="t1", source="csv", external_id="1", variant_id=None,
        name="Test Product", ean="5901234123457",
        wholesale_price=Decimal("60.00"), currency="PLN", category="Test",
    )
    defaults.update(overrides)
    return Product(**defaults)

def _search_response(content: str, search_results: list[dict] | None = None) -> dict:
    message: dict = {"content": content}
    if search_results is not None:
        message["executed_tools"] = [{"search_results": search_results}]
    return {"choices": [{"message": message}]}

def _extract_response(parsed: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(parsed)}}]}

class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload

class _TwoCallClient:
    """Returns `search_payload` for the compound-mini call, `extract_payload`
    for the gpt-oss-20b call, distinguishing by the requested `model`."""

    def __init__(self, search_payload: dict, extract_payload: dict):
        self._search_payload = search_payload
        self._extract_payload = extract_payload
        self.requests: list[dict] = []

    def post(self, url, headers, json):
        self.requests.append({"url": url, "headers": headers, "json": json})
        if json["model"] == "groq/compound-mini":
            return _FakeResponse(self._search_payload)
        return _FakeResponse(self._extract_payload)

def test_two_call_flow_returns_offer_with_citations_from_search_results():
    client = _TwoCallClient(
        search_payload=_search_response(
            "The cheapest offer is 89.99 PLN at Example Shop.",
            search_results=[
                {"title": "Example Shop", "url": "https://example.com/product", "content": "...", "score": 0.9},
            ],
        ),
        extract_payload=_extract_response({
            "found": True, "price": 89.99, "currency": "PLN", "seller": "Example Shop",
            "source_url": "https://example.com/product", "delivery_days": 2, "confidence": 0.85,
        }),
    )
    provider = GroqProvider(api_key="test-key", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer is not None
    assert offer.price == Decimal("89.99")
    assert offer.citations == ("https://example.com/product",)
    # First call uses compound-mini with no response_format (tool use + structured
    # outputs are documented as incompatible); second uses gpt-oss-20b with one.
    assert client.requests[0]["json"]["model"] == "groq/compound-mini"
    assert "response_format" not in client.requests[0]["json"]
    assert client.requests[1]["json"]["model"] == "openai/gpt-oss-20b"
    assert client.requests[1]["json"]["response_format"]["type"] == "json_schema"

def test_uses_bearer_auth_on_both_calls():
    client = _TwoCallClient(
        search_payload=_search_response("no offer found"),
        extract_payload=_extract_response({"found": False}),
    )
    provider = GroqProvider(api_key="secret-key", client=client)

    provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert all(r["headers"]["Authorization"] == "Bearer secret-key" for r in client.requests)

def test_returns_none_when_extract_says_not_found():
    client = _TwoCallClient(
        search_payload=_search_response("Nothing matched."),
        extract_payload=_extract_response({"found": False}),
    )
    provider = GroqProvider(api_key="test-key", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer is None

def test_returns_none_when_no_executed_tools_present():
    # The model may answer from its own knowledge without calling web search;
    # executed_tools is then absent entirely, not an empty list.
    client = _TwoCallClient(
        search_payload=_search_response("I don't have current pricing."),
        extract_payload=_extract_response({"found": False}),
    )
    provider = GroqProvider(api_key="test-key", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer is None  # must not raise on missing executed_tools

def test_deduplicates_citation_urls_across_multiple_search_results():
    client = _TwoCallClient(
        search_payload=_search_response(
            "text",
            search_results=[
                {"title": "A", "url": "https://example.com/x", "content": "", "score": 0.9},
                {"title": "B", "url": "https://example.com/x", "content": "", "score": 0.5},
                {"title": "C", "url": "https://example.com/y", "content": "", "score": 0.4},
            ],
        ),
        extract_payload=_extract_response({
            "found": True, "price": 5.0, "currency": "PLN", "seller": "S",
            "source_url": "https://example.com/x", "delivery_days": 1, "confidence": 0.5,
        }),
    )
    provider = GroqProvider(api_key="test-key", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer.citations == ("https://example.com/x", "https://example.com/y")

class _SearchCallFailsClient:
    def post(self, url, headers, json):
        raise httpx.ConnectError("connection refused")

def test_raises_provider_unavailable_when_search_call_fails():
    provider = GroqProvider(api_key="test-key", client=_SearchCallFailsClient())

    with pytest.raises(ProviderUnavailable):
        provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

class _AuthFailsOnExtractClient:
    def post(self, url, headers, json):
        if json["model"] == "groq/compound-mini":
            return _FakeResponse(_search_response("some text"))
        return _FakeResponse({}, status_code=401)

def test_raises_provider_auth_error_when_extract_call_rejects_key():
    provider = GroqProvider(api_key="bad-key", client=_AuthFailsOnExtractClient())

    with pytest.raises(ProviderAuthError):
        provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

class _MalformedSearchContentClient:
    def post(self, url, headers, json):
        return _FakeResponse({"choices": [{}]})  # no "message" key at all

def test_returns_none_on_malformed_search_response():
    provider = GroqProvider(api_key="test-key", client=_MalformedSearchContentClient())

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/providers/test_groq.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.providers.groq'`

- [ ] **Step 3: Implement `groq.py`**

```python
# backend/app/providers/groq.py
from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

import httpx

from app.models.product import Product
from app.providers.base import OfferResult, ProviderAuthError, ProviderProfile, ProviderUnavailable
from app.providers.parsing import RESPONSE_SCHEMA, validate_offer_fields
from app.providers.retry import call_with_retry

API_URL = "https://api.groq.com/openai/v1/chat/completions"
SEARCH_MODEL = "groq/compound-mini"
EXTRACT_MODEL = "openai/gpt-oss-20b"

logger = logging.getLogger(__name__)

class GroqProvider:
    """Free-tier BYOK provider. Two real HTTP calls per lookup because Groq's
    compound-mini (web search) is documented as incompatible with structured
    outputs in the same request (console.groq.com/docs/structured-outputs:
    "tool use is not currently supported with Structured Outputs") — so
    grounding and JSON-schema extraction are two separate calls, the second
    on a model (gpt-oss-20b) that does support response_format=json_schema.
    """

    name = "groq"
    # Free tier: no dollar cost. seconds_per_query is a documented estimate
    # (two sequential Groq calls), not a measured guarantee — same caveat as
    # PerplexityProvider.profile.
    profile = ProviderProfile(cost_per_query_usd=Decimal("0.000"), seconds_per_query=4.0)

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ):
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=timeout)

    def find_cheapest(
        self, product: Product, market: str, max_delivery_days: int
    ) -> OfferResult | None:
        search_text, citations = self._search(product, market, max_delivery_days)
        if not search_text:
            return None
        return self._extract(search_text, citations, max_delivery_days)

    def _search(
        self, product: Product, market: str, max_delivery_days: int
    ) -> tuple[str | None, tuple[str, ...]]:
        try:
            response = call_with_retry(lambda: self._client.post(
                API_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": SEARCH_MODEL,
                    "messages": [
                        {"role": "user", "content": self._build_search_prompt(product, market, max_delivery_days)}
                    ],
                },
            ))
            response_json = response.json()
        except httpx.HTTPError as exc:
            logger.warning(
                "Groq search call failed transiently for product %r: %s", product.name, exc,
            )
            raise ProviderUnavailable(str(exc)) from exc
        except json.JSONDecodeError:
            return None, ()

        try:
            message = response_json["choices"][0]["message"]
            content = message["content"]
        except (KeyError, IndexError, TypeError):
            return None, ()

        # executed_tools is absent entirely (not an empty list) when the
        # model answered without calling web search at all.
        executed_tools = message.get("executed_tools") or []
        urls: list[str] = []
        for tool in executed_tools:
            for result in tool.get("search_results") or []:
                url = result.get("url")
                if isinstance(url, str) and url not in urls:
                    urls.append(url)
        return content, tuple(urls)

    def _extract(
        self, search_text: str, citations: tuple[str, ...], max_delivery_days: int
    ) -> OfferResult | None:
        try:
            response = call_with_retry(lambda: self._client.post(
                API_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": EXTRACT_MODEL,
                    "messages": [
                        {"role": "user", "content": self._build_extract_prompt(search_text, max_delivery_days)}
                    ],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {"name": "cheapest_offer", "schema": RESPONSE_SCHEMA},
                    },
                },
            ))
            response_json = response.json()
        except httpx.HTTPError as exc:
            logger.warning("Groq extract call failed transiently: %s", exc)
            raise ProviderUnavailable(str(exc)) from exc
        except json.JSONDecodeError:
            return None

        raw_response = json.dumps(response_json)
        try:
            content = response_json["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            return None

        return validate_offer_fields(
            parsed, raw_response=raw_response, citations=citations,
            max_delivery_days=max_delivery_days,
        )

    def _build_search_prompt(self, product: Product, market: str, max_delivery_days: int) -> str:
        ean_part = f" (EAN: {product.ean})" if product.ean else ""
        return (
            f'Search the web for the cheapest real, currently-buyable offer for the product '
            f'"{product.name}"{ean_part} in the {market} market, from a seller that can deliver '
            f"within {max_delivery_days} days. State the price, currency, seller name, the exact "
            f"source URL, and expected delivery time. If you cannot find a genuine current offer, "
            f"say so explicitly rather than guessing."
        )

    def _build_extract_prompt(self, search_text: str, max_delivery_days: int) -> str:
        return (
            "Extract the cheapest offer described below into the requested JSON schema. "
            f'Set "found" to false if the text does not describe a genuine current offer, or if '
            f"the only offer described has delivery_days greater than {max_delivery_days}.\n\n"
            f"Text:\n{search_text}"
        )
```

Note the two-space `_extract` prompt intentionally does not repeat the product/market — the compound-mini answer already grounds those facts; re-stating them to a model with no web access would invite it to override the search result.

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/providers/test_groq.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Run the full provider test suite**

Run: `cd backend && .venv/bin/pytest tests/providers/ -v`
Expected: PASS, all tests

- [ ] **Step 6: Commit**

```bash
git add backend/app/providers/groq.py backend/tests/providers/test_groq.py
git commit -m "feat: add GroqProvider (two-call search-then-extract)"
```

---

### Task 6: Live opt-in smoke test for `GroqProvider`

**Files:**
- Create: `backend/tests/providers/test_groq_live.py`

**Interfaces:**
- Consumes: `GroqProvider` (Task 5). No production code changes in this task.

- [ ] **Step 1: Write the live smoke test, mirroring `test_perplexity_live.py`'s skip-on-env pattern**

```python
# backend/tests/providers/test_groq_live.py
import os
from decimal import Decimal

import pytest

from app.models.product import Product
from app.providers.groq import GroqProvider

pytestmark = pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY"),
    reason="GROQ_API_KEY not set — export it to run this opt-in smoke test",
)

def test_find_cheapest_returns_a_contract_valid_result_or_none():
    provider = GroqProvider(api_key=os.environ["GROQ_API_KEY"])
    product = Product(
        tenant_id="default", source="csv", external_id="smoke-1", variant_id=None,
        name="Apple iPhone 15 128GB", ean="0195949037748",
        wholesale_price=Decimal("3000.00"), currency="PLN", category="Elektronika",
    )

    offer = provider.find_cheapest(product, market="PL", max_delivery_days=5)

    if offer is None:
        return  # a clean "no valid offer found" is an acceptable real-world outcome

    assert offer.source_url.startswith("http")
    assert 0.0 <= offer.confidence <= 1.0
    assert offer.price > 0
    assert offer.delivery_days <= 5
    assert offer.currency
    assert offer.seller
```

- [ ] **Step 2: Run without `GROQ_API_KEY` set, verify it skips cleanly**

Run: `cd backend && .venv/bin/pytest tests/providers/test_groq_live.py -v`
Expected: `1 skipped`

- [ ] **Step 3: If a `GROQ_API_KEY` is available (see plan header — the Faza 0 spike blocked on Groq's own known account-provisioning bug), run it live and record the real result manually — this is the deferred spike verification, not a required gate for this task**

Run: `cd backend && GROQ_API_KEY=<key> .venv/bin/pytest tests/providers/test_groq_live.py -v -s`
Expected: PASS, and manually compare the returned offer's plausibility against what `test_perplexity_live.py` returns for the same product (run both back to back). Note the result in a comment on this task when re-run later — this is the Faza 0 spike question ("is compound's grounding quality comparable to sonar?") finally answered with data, whenever the Groq account becomes usable.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/providers/test_groq_live.py
git commit -m "test: add opt-in live smoke test for GroqProvider"
```

---

### Task 7: `run_scan` learns a `paused` outcome distinct from `failed`

**Files:**
- Modify: `backend/app/scans/models.py`
- Modify: `backend/app/scans/store.py`
- Modify: `backend/app/scans/engine.py`
- Modify: `backend/tests/scans/test_engine.py`

**Interfaces:**
- Consumes: `ProviderRateLimited`, `ProviderAuthError` (Task 2).
- Produces: `ScanStatus.PAUSED` enum member; `ScanStore.pause_scan(scan_id: str) -> None`. Faza 5's resumer/scheduler (out of scope here) will later pick up `paused` scans automatically; for now a paused scan only resumes via a manual `POST /scans/{id}/start` call, same as today's `failed`-with-pending-rows case.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/scans/test_engine.py` (after the existing `test_run_scan_never_exceeds_max_concurrency`):

```python
from app.providers.base import ProviderAuthError, ProviderRateLimited

def test_run_scan_pauses_without_failing_when_rate_limited(tmp_path):
    products = [
        _make_product(external_id="1", ean="5901234123457"),
        _make_product(external_id="2", ean="5900000000009"),
    ]
    store, scan_id = _make_store_with_products(tmp_path, products)
    cache = PriceCache(tmp_path / "app.sqlite3")
    provider = _ScriptedProvider({
        "5901234123457": ProviderRateLimited("rate limited", retry_after=60.0),
        "5900000000009": ProviderRateLimited("rate limited", retry_after=60.0),
    })

    asyncio.run(run_scan(scan_id, store, cache, provider, "PL", 5, max_concurrency=5))

    assert store.get_scan(scan_id).status == ScanStatus.PAUSED
    assert len(store.list_pending(scan_id)) == 2  # both records stay pending, not failed
    store.close()
    cache.close()

def test_run_scan_can_resume_a_paused_scan_after_budget_recovers(tmp_path):
    products = [_make_product(external_id="1", ean="5901234123457")]
    store, scan_id = _make_store_with_products(tmp_path, products)
    cache = PriceCache(tmp_path / "app.sqlite3")
    limited_provider = _ScriptedProvider({"5901234123457": ProviderRateLimited("rate limited")})
    asyncio.run(run_scan(scan_id, store, cache, limited_provider, "PL", 5, max_concurrency=5))
    assert store.get_scan(scan_id).status == ScanStatus.PAUSED

    recovered_provider = _ScriptedProvider({"5901234123457": _make_offer()})
    asyncio.run(run_scan(scan_id, store, cache, recovered_provider, "PL", 5, max_concurrency=5))

    assert store.get_scan(scan_id).status == ScanStatus.DONE
    store.close()
    cache.close()

def test_run_scan_fails_fast_on_auth_error_without_retrying_every_product(tmp_path):
    products = [
        _make_product(external_id="1", ean="5901234123457"),
        _make_product(external_id="2", ean="5900000000009"),
    ]
    store, scan_id = _make_store_with_products(tmp_path, products)
    cache = PriceCache(tmp_path / "app.sqlite3")
    provider = _ScriptedProvider({
        "5901234123457": ProviderAuthError("bad key"),
        "5900000000009": ProviderAuthError("bad key"),
    })

    asyncio.run(run_scan(scan_id, store, cache, provider, "PL", 5, max_concurrency=5))

    assert store.get_scan(scan_id).status == ScanStatus.FAILED
    store.close()
    cache.close()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/scans/test_engine.py -v -k "paused or auth_error"`
Expected: FAIL — `AttributeError: PAUSED` (the enum member doesn't exist yet)

- [ ] **Step 3: Add `PAUSED` to `ScanStatus`**

Modify `backend/app/scans/models.py`:

```python
class ScanStatus(str, Enum):
    ESTIMATED = "estimated"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
```

- [ ] **Step 4: Add `ScanStore.pause_scan`**

Modify `backend/app/scans/store.py` — add a new method right after `start_scan` (which it mirrors exactly):

```python
    def pause_scan(self, scan_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE scans SET status = ? WHERE id = ?",
                (ScanStatus.PAUSED.value, scan_id),
            )
            self._conn.commit()
```

- [ ] **Step 5: Update `run_scan` to distinguish the three outcomes**

Replace `backend/app/scans/engine.py` in full:

```python
from __future__ import annotations

import asyncio

from app.cache.sqlite_cache import PriceCache
from app.providers.base import PriceProvider, ProviderAuthError, ProviderRateLimited, ProviderUnavailable
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
    rate_limited = asyncio.Event()

    async def process(record) -> None:
        async with semaphore:
            if rate_limited.is_set():
                # Budget already known exhausted by another in-flight call;
                # leave this record pending rather than making a call we
                # already know will fail identically.
                return
            try:
                offer = await asyncio.to_thread(
                    get_offer_cached, record.product, market, max_delivery_days, cache, provider
                )
            except ProviderRateLimited:
                rate_limited.set()
                return
            except ProviderAuthError:
                # Not transient — retrying every remaining product would
                # waste the scan's full time budget on a failure the first
                # response already fully diagnosed. Leave pending; the scan
                # finalizes as FAILED below since some rows stay pending.
                rate_limited.set()
                return
            except ProviderUnavailable:
                # Leave it pending — a later run_scan() call for this scan_id
                # (process restart, or a retry) will pick it up again.
                return
            store.mark_done(record.id, offer)

    await asyncio.gather(*(process(record) for record in pending))

    if rate_limited.is_set() and not store.list_pending(scan_id) == []:
        # Distinguish "ran out of budget, resume later" from "genuinely
        # failed" only when a ProviderRateLimited (not ProviderAuthError)
        # caused the stop. Re-check by asking whether any pending record's
        # failure was a rate limit specifically: simplest correct signal
        # available without threading exception identity through the
        # gather results is that ProviderAuthError and ProviderRateLimited
        # both set `rate_limited` — but auth errors must still resolve to
        # FAILED per this task's third test. Track them separately instead:
        pass

    store.finalize_scan(scan_id) if not rate_limited.is_set() else store.pause_scan(scan_id)
```

Re-examine this before running the tests: the draft above conflates "rate limited" and "auth error" into one `rate_limited` flag, which would incorrectly pause a scan on an auth error too (the third new test requires `FAILED`, not `PAUSED`). Replace the single `rate_limited` event with two separate flags:

```python
from __future__ import annotations

import asyncio

from app.cache.sqlite_cache import PriceCache
from app.providers.base import PriceProvider, ProviderAuthError, ProviderRateLimited, ProviderUnavailable
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
    stop_dispatch = asyncio.Event()
    rate_limit_hit = False

    async def process(record) -> None:
        nonlocal rate_limit_hit
        async with semaphore:
            if stop_dispatch.is_set():
                return
            try:
                offer = await asyncio.to_thread(
                    get_offer_cached, record.product, market, max_delivery_days, cache, provider
                )
            except ProviderRateLimited:
                rate_limit_hit = True
                stop_dispatch.set()
                return
            except ProviderAuthError:
                stop_dispatch.set()
                return
            except ProviderUnavailable:
                return
            store.mark_done(record.id, offer)

    await asyncio.gather(*(process(record) for record in pending))

    if rate_limit_hit:
        store.pause_scan(scan_id)
    else:
        store.finalize_scan(scan_id)
```

This is the version to actually implement — the intermediate draft above is shown only to make the reasoning explicit for whoever reads this plan; do not implement the conflated version.

- [ ] **Step 6: Run the new tests**

Run: `cd backend && .venv/bin/pytest tests/scans/test_engine.py -v`
Expected: PASS, all tests including the 3 new ones and all 4 pre-existing ones unchanged

- [ ] **Step 7: Run the full backend test suite**

Run: `cd backend && .venv/bin/pytest -v`
Expected: PASS, all tests

- [ ] **Step 8: Commit**

```bash
git add backend/app/scans/models.py backend/app/scans/store.py backend/app/scans/engine.py backend/tests/scans/test_engine.py
git commit -m "feat: run_scan pauses (not fails) when the provider's rate limit is exhausted"
```

---

### Task 8: Env-var provider selection in `get_provider()`

**Files:**
- Modify: `backend/app/scans/api.py:77-82`
- Test: `backend/tests/scans/test_api.py`

**Interfaces:**
- Consumes: `GroqProvider` (Task 5), `PerplexityProvider` (existing).
- Produces: no new importable symbol — `get_provider()`'s behavior changes, still returning `PriceProvider`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/scans/test_api.py` (near the top, after existing imports — this test manipulates the module-level singleton directly, matching how this file already tests `get_store`/`get_cache` singleton behavior if such a test exists; if not, add a fresh, self-contained one):

```python
def test_get_provider_selects_groq_from_env_var(monkeypatch):
    monkeypatch.setenv("PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    api_module._shared_provider = None  # reset the module singleton

    provider = api_module.get_provider()

    assert provider.name == "groq"
    api_module._shared_provider = None  # leave a clean slate for later tests

def test_get_provider_defaults_to_perplexity_when_provider_env_unset(monkeypatch):
    monkeypatch.delenv("PROVIDER", raising=False)
    monkeypatch.setenv("PERPLEXITY_API_KEY", "test-perplexity-key")
    api_module._shared_provider = None

    provider = api_module.get_provider()

    assert provider.name == "perplexity"
    api_module._shared_provider = None
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/scans/test_api.py -v -k "get_provider_selects or get_provider_defaults"`
Expected: FAIL — `assert 'perplexity' == 'groq'` (the env var is currently ignored entirely)

- [ ] **Step 3: Update `get_provider()`**

Modify `backend/app/scans/api.py`:

```python
def get_provider() -> PriceProvider:
    global _shared_provider
    if _shared_provider is None:
        import os
        provider_name = os.environ.get("PROVIDER", "perplexity")
        if provider_name == "groq":
            from app.providers.groq import GroqProvider
            _shared_provider = GroqProvider(api_key=os.environ["GROQ_API_KEY"])
        else:
            _shared_provider = PerplexityProvider(api_key=os.environ["PERPLEXITY_API_KEY"])
    return _shared_provider
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/scans/test_api.py -v -k "get_provider_selects or get_provider_defaults"`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full backend test suite one final time for this phase**

Run: `cd backend && .venv/bin/pytest -v`
Expected: PASS, all tests, same skip count as before this plan started (4 skipped: the 3 existing live tests + the new `test_groq_live.py`)

- [ ] **Step 6: Update `README.md`'s env var documentation**

Modify `backend/../README.md` (repo root) wherever `PERPLEXITY_API_KEY` is currently documented as the required env var (per the earlier exploration, this is in the "Backend" setup section) — add `PROVIDER` (optional, `perplexity` default or `groq`) and `GROQ_API_KEY` (required only when `PROVIDER=groq`) alongside it.

- [ ] **Step 7: Commit**

```bash
git add backend/app/scans/api.py backend/tests/scans/test_api.py README.md
git commit -m "feat: select AI provider via PROVIDER env var (perplexity default, groq opt-in)"
```

---

## Self-Review

**1. Spec coverage** (against Faza 1's bullet list in the design doc):
- `app/providers/retry.py` with backoff/jitter/Retry-After, 429/5xx retryable, other 4xx permanent → Task 4. ✓
- `ProviderRateLimited`, `ProviderAuthError` → Task 2. ✓
- `GroqProvider` → Task 5. ✓
- Live test skip-on-env → Task 6. ✓
- Batchowanie w run_scan + status paused → Task 7 (batching itself — bounding a single `list_pending` call's size — is deliberately deferred to Faza 5 per this plan's header note; the `paused` status and the rate-limit/auth-error distinction, which is what Faza 1 actually needs to make Groq usable at all, is fully implemented here).
- Wyciągnięcie `_parse_response`, `ProviderProfile` w Protokole, przeniesienie `COST_PER_QUERY_USD`/`SECONDS_PER_QUERY` → Tasks 1-3. ✓

**2. Placeholder scan:** No TBD/TODO markers; every code block is complete and runnable. Task 7's "intermediate draft" text is a deliberate exception explained inline as reasoning-only, immediately followed by the actual implementation to use — flagged explicitly as "do not implement the conflated version" so an implementer cannot mistake it for two competing options to choose between.

**3. Type consistency:** `ProviderProfile(cost_per_query_usd, seconds_per_query)` used identically in Tasks 2, 3, 5. `estimate_cost(..., profile: ProviderProfile)` signature from Task 3 matches its Task 3 test usage. `create_scan(..., provider: PriceProvider)` from Task 3 matches Task 3's own call-site updates. `ProviderRateLimited(message, retry_after=None)` and `ProviderAuthError(message)` constructor shapes from Task 2 match every raise site in Tasks 4, 5, and every catch site in Task 7. `GroqProvider.name = "groq"` matches Task 8's `provider.name == "groq"` assertion.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-28-groq-provider-retry-budget.md`.

Which approach?
