# Phase 3 — Price Provider Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the price-discovery layer: a `PriceProvider` protocol, a Perplexity Sonar
implementation with structured JSON output, an SQLite result cache, and anomaly detection —
so that, given a `Product`, the system can find the cheapest real market offer meeting a
delivery-time constraint, without ever paying twice for the same lookup and without trusting
an unsourced price.

**Architecture:** Mirrors the existing `sources/` package. `providers/base.py` defines the
`PriceProvider` protocol and the `OfferResult` contract every provider must satisfy.
`providers/perplexity.py` is the only implementation (Sonar `/chat/completions`, structured
JSON output). `cache/sqlite_cache.py` is a provider-agnostic SQLite cache keyed on
`(ean, market, provider, max_delivery_days)`, storing both hits and negative results (no
offer found) so a repeat scan never re-queries the same product. `providers/anomaly.py` flags
suspicious offers (price below wholesale, absurdly high, or low LLM confidence) without
rejecting them outright — the report layer (later phase) decides how to surface flags.
`providers/lookup.py` is the thin orchestration function gluing cache + provider together;
it is the only entry point the future job engine (Phase 4) will call.

**Tech Stack:** Python, `httpx` (already a dependency) for the Perplexity HTTP call, stdlib
`sqlite3` for the cache — no new dependencies.

## Global Constraints

- Money is always `Decimal`, never `float` (existing project rule — see `backend/app/pricing/margin.py`).
- Currency is explicit on every offer; this phase does **not** do currency conversion — offers are
  assumed to already be in the requested market's currency (PLN for market `"PL"`). Out of scope: reject
  nothing based on currency mismatch, just record what the provider returns.
- An offer without a `source_url` is invalid and must never become an `OfferResult` — surface as `None`
  ("no valid offer found"), never raise.
- `max_delivery_days` is a hard filter: an offer whose `delivery_days` exceeds it is invalid, same as
  above (must produce `None`, not a filtered-but-returned result).
- Never pay twice for the same `(ean, market, provider, max_delivery_days)` — the cache must store
  negative results (provider found nothing), not just hits.
- No new runtime dependencies beyond what `backend/requirements.txt` already has (`httpx` covers the
  HTTP call).
- Real Perplexity API calls are opt-in only, gated on the `PERPLEXITY_API_KEY` environment variable.
  Every unit test in this plan must run to completion with **zero** network calls — only the final,
  explicitly-gated smoke test hits the real API.
- Follow existing test conventions: no shared `conftest.py` fixtures exist yet in `backend/tests/` —
  each test file defines its own local `_make_product(**overrides)` style helper (see
  `backend/tests/models/test_product.py`, `backend/tests/pricing/test_margin.py`).

---

## File Structure

- Create: `backend/app/providers/__init__.py` — empty, marks package
- Create: `backend/app/providers/base.py` — `OfferResult` dataclass, `PriceProvider` protocol
- Create: `backend/app/providers/anomaly.py` — `AnomalyFlag` enum, `detect_anomaly()`
- Create: `backend/app/providers/perplexity.py` — `PerplexityProvider` (prompt building, HTTP call, response parsing)
- Create: `backend/app/providers/lookup.py` — `get_offer_cached()`, the cache+provider orchestration entry point
- Create: `backend/app/cache/__init__.py` — empty, marks package
- Create: `backend/app/cache/sqlite_cache.py` — `CacheEntry` dataclass, `PriceCache` class
- Test: `backend/tests/providers/__init__.py`
- Test: `backend/tests/providers/test_base.py`
- Test: `backend/tests/providers/test_anomaly.py`
- Test: `backend/tests/providers/test_perplexity.py` (fully mocked HTTP client — no network)
- Test: `backend/tests/providers/test_lookup.py`
- Test: `backend/tests/providers/test_perplexity_live.py` (opt-in real API smoke test)
- Test: `backend/tests/cache/__init__.py`
- Test: `backend/tests/cache/test_sqlite_cache.py`

---

## Task 1: `OfferResult` + `PriceProvider` protocol

**Files:**
- Create: `backend/app/providers/__init__.py`
- Create: `backend/app/providers/base.py`
- Test: `backend/tests/providers/__init__.py`
- Test: `backend/tests/providers/test_base.py`

**Interfaces:**
- Produces: `OfferResult` frozen dataclass with fields `price: Decimal`, `currency: str`,
  `seller: str`, `source_url: str`, `delivery_days: int`, `confidence: float`,
  `citations: tuple[str, ...]`, `raw_response: str`.
- Produces: `PriceProvider` Protocol with `find_cheapest(self, product: Product, market: str, max_delivery_days: int) -> OfferResult | None`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/providers/test_base.py
import dataclasses
from decimal import Decimal

from app.providers.base import OfferResult


def _make_offer(**overrides) -> OfferResult:
    defaults = dict(
        price=Decimal("99.99"),
        currency="PLN",
        seller="Example Shop",
        source_url="https://example.com/product",
        delivery_days=3,
        confidence=0.9,
        citations=("https://example.com/product",),
        raw_response='{"raw": true}',
    )
    defaults.update(overrides)
    return OfferResult(**defaults)


def test_offer_result_holds_all_contract_fields():
    offer = _make_offer()
    assert offer.price == Decimal("99.99")
    assert offer.currency == "PLN"
    assert offer.seller == "Example Shop"
    assert offer.source_url == "https://example.com/product"
    assert offer.delivery_days == 3
    assert offer.confidence == 0.9
    assert offer.citations == ("https://example.com/product",)
    assert offer.raw_response == '{"raw": true}'


def test_offer_result_is_frozen():
    offer = _make_offer()
    with __import__("pytest").raises(dataclasses.FrozenInstanceError):
        offer.price = Decimal("1.00")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/providers/test_base.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.providers'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/providers/__init__.py
```

```python
# backend/app/providers/base.py
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from app.models.product import Product


@dataclass(frozen=True)
class OfferResult:
    price: Decimal
    currency: str
    seller: str
    source_url: str
    delivery_days: int
    confidence: float
    citations: tuple[str, ...]
    raw_response: str


class PriceProvider(Protocol):
    name: str

    def find_cheapest(
        self, product: Product, market: str, max_delivery_days: int
    ) -> OfferResult | None:
        ...
```

```python
# backend/tests/providers/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/providers/test_base.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/providers/__init__.py backend/app/providers/base.py backend/tests/providers/__init__.py backend/tests/providers/test_base.py
git commit -m "Add OfferResult contract and PriceProvider protocol"
```

---

## Task 2: Anomaly detection

**Files:**
- Create: `backend/app/providers/anomaly.py`
- Test: `backend/tests/providers/test_anomaly.py`

**Interfaces:**
- Consumes: `OfferResult` from Task 1 (`app.providers.base.OfferResult`).
- Produces: `AnomalyFlag` enum (`BELOW_WHOLESALE`, `UNUSUALLY_HIGH`, `LOW_CONFIDENCE`) and
  `detect_anomaly(offer: OfferResult, wholesale_price: Decimal) -> AnomalyFlag | None`, used by
  Task 5's `lookup.py` and later by the report layer.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/providers/test_anomaly.py
from decimal import Decimal

from app.providers.anomaly import AnomalyFlag, detect_anomaly
from app.providers.base import OfferResult


def _make_offer(**overrides) -> OfferResult:
    defaults = dict(
        price=Decimal("100.00"),
        currency="PLN",
        seller="Example Shop",
        source_url="https://example.com/product",
        delivery_days=3,
        confidence=0.9,
        citations=("https://example.com/product",),
        raw_response="{}",
    )
    defaults.update(overrides)
    return OfferResult(**defaults)


def test_no_anomaly_for_reasonable_offer():
    offer = _make_offer(price=Decimal("100.00"), confidence=0.9)
    assert detect_anomaly(offer, wholesale_price=Decimal("60.00")) is None


def test_flags_price_below_wholesale():
    offer = _make_offer(price=Decimal("50.00"), confidence=0.9)
    assert detect_anomaly(offer, wholesale_price=Decimal("60.00")) == AnomalyFlag.BELOW_WHOLESALE


def test_flags_unusually_high_price():
    offer = _make_offer(price=Decimal("1000.00"), confidence=0.9)
    assert detect_anomaly(offer, wholesale_price=Decimal("60.00")) == AnomalyFlag.UNUSUALLY_HIGH


def test_flags_low_confidence_before_price_checks():
    offer = _make_offer(price=Decimal("50.00"), confidence=0.2)
    assert detect_anomaly(offer, wholesale_price=Decimal("60.00")) == AnomalyFlag.LOW_CONFIDENCE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/providers/test_anomaly.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.providers.anomaly'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/providers/anomaly.py
from __future__ import annotations

from decimal import Decimal
from enum import Enum

from app.providers.base import OfferResult

LOW_CONFIDENCE_THRESHOLD = 0.5
HIGH_PRICE_MULTIPLIER = Decimal("10")


class AnomalyFlag(str, Enum):
    BELOW_WHOLESALE = "below_wholesale"
    UNUSUALLY_HIGH = "unusually_high"
    LOW_CONFIDENCE = "low_confidence"


def detect_anomaly(offer: OfferResult, wholesale_price: Decimal) -> AnomalyFlag | None:
    if offer.confidence < LOW_CONFIDENCE_THRESHOLD:
        return AnomalyFlag.LOW_CONFIDENCE
    if offer.price < wholesale_price:
        return AnomalyFlag.BELOW_WHOLESALE
    if offer.price > wholesale_price * HIGH_PRICE_MULTIPLIER:
        return AnomalyFlag.UNUSUALLY_HIGH
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/providers/test_anomaly.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/providers/anomaly.py backend/tests/providers/test_anomaly.py
git commit -m "Add anomaly detection for suspicious price offers"
```

---

## Task 3: SQLite `PriceCache`

**Files:**
- Create: `backend/app/cache/__init__.py`
- Create: `backend/app/cache/sqlite_cache.py`
- Test: `backend/tests/cache/__init__.py`
- Test: `backend/tests/cache/test_sqlite_cache.py`

**Interfaces:**
- Consumes: `OfferResult` from Task 1.
- Produces: `CacheEntry` frozen dataclass (`found: bool`, `offer: OfferResult | None`,
  `cached_at: float`) and `PriceCache` with `__init__(self, db_path, ttl_seconds=2592000)`,
  `get(self, ean, market, provider, max_delivery_days) -> CacheEntry | None`,
  `set(self, ean, market, provider, max_delivery_days, offer) -> None` (pass `offer=None` to
  cache a negative result), `close(self) -> None`. Used by Task 5's `lookup.py`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/cache/test_sqlite_cache.py
import time
from decimal import Decimal

from app.cache.sqlite_cache import PriceCache
from app.providers.base import OfferResult


def _make_offer(**overrides) -> OfferResult:
    defaults = dict(
        price=Decimal("99.99"),
        currency="PLN",
        seller="Example Shop",
        source_url="https://example.com/product",
        delivery_days=3,
        confidence=0.9,
        citations=("https://example.com/product", "https://example.com/review"),
        raw_response='{"raw": true}',
    )
    defaults.update(overrides)
    return OfferResult(**defaults)


def test_miss_on_empty_cache(tmp_path):
    cache = PriceCache(tmp_path / "cache.sqlite3")
    assert cache.get("5901234123457", "PL", "perplexity", 5) is None
    cache.close()


def test_round_trips_a_hit(tmp_path):
    cache = PriceCache(tmp_path / "cache.sqlite3")
    offer = _make_offer()
    cache.set("5901234123457", "PL", "perplexity", 5, offer)

    entry = cache.get("5901234123457", "PL", "perplexity", 5)

    assert entry is not None
    assert entry.found is True
    assert entry.offer == offer
    cache.close()


def test_caches_a_negative_result(tmp_path):
    cache = PriceCache(tmp_path / "cache.sqlite3")
    cache.set("5901234123457", "PL", "perplexity", 5, None)

    entry = cache.get("5901234123457", "PL", "perplexity", 5)

    assert entry is not None
    assert entry.found is False
    assert entry.offer is None
    cache.close()


def test_different_cache_key_dimensions_are_isolated(tmp_path):
    cache = PriceCache(tmp_path / "cache.sqlite3")
    offer = _make_offer()
    cache.set("5901234123457", "PL", "perplexity", 5, offer)

    assert cache.get("5901234123457", "PL", "perplexity", 3) is None
    assert cache.get("5901234123457", "DE", "perplexity", 5) is None
    assert cache.get("0000000000017", "PL", "perplexity", 5) is None
    cache.close()


def test_expired_entry_is_treated_as_a_miss(tmp_path):
    cache = PriceCache(tmp_path / "cache.sqlite3", ttl_seconds=1)
    cache.set("5901234123457", "PL", "perplexity", 5, _make_offer())

    time.sleep(1.1)

    assert cache.get("5901234123457", "PL", "perplexity", 5) is None
    cache.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/cache/test_sqlite_cache.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.cache'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/cache/__init__.py
```

```python
# backend/app/cache/sqlite_cache.py
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from app.providers.base import OfferResult

DEFAULT_TTL_SECONDS = 30 * 24 * 3600


@dataclass(frozen=True)
class CacheEntry:
    found: bool
    offer: OfferResult | None
    cached_at: float


class PriceCache:
    def __init__(self, db_path: str | Path, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self._conn = sqlite3.connect(str(db_path))
        self._ttl_seconds = ttl_seconds
        self._create_schema()

    def _create_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS price_cache (
                ean TEXT NOT NULL,
                market TEXT NOT NULL,
                provider TEXT NOT NULL,
                max_delivery_days INTEGER NOT NULL,
                found INTEGER NOT NULL,
                price TEXT,
                currency TEXT,
                seller TEXT,
                source_url TEXT,
                delivery_days INTEGER,
                confidence REAL,
                citations TEXT,
                raw_response TEXT,
                cached_at REAL NOT NULL,
                PRIMARY KEY (ean, market, provider, max_delivery_days)
            )
            """
        )
        self._conn.commit()

    def get(
        self, ean: str, market: str, provider: str, max_delivery_days: int
    ) -> CacheEntry | None:
        row = self._conn.execute(
            """
            SELECT found, price, currency, seller, source_url, delivery_days,
                   confidence, citations, raw_response, cached_at
            FROM price_cache
            WHERE ean = ? AND market = ? AND provider = ? AND max_delivery_days = ?
            """,
            (ean, market, provider, max_delivery_days),
        ).fetchone()
        if row is None:
            return None

        (
            found, price, currency, seller, source_url, delivery_days,
            confidence, citations, raw_response, cached_at,
        ) = row

        if time.time() - cached_at > self._ttl_seconds:
            return None

        if not found:
            return CacheEntry(found=False, offer=None, cached_at=cached_at)

        offer = OfferResult(
            price=Decimal(price),
            currency=currency,
            seller=seller,
            source_url=source_url,
            delivery_days=delivery_days,
            confidence=confidence,
            citations=tuple(json.loads(citations)),
            raw_response=raw_response,
        )
        return CacheEntry(found=True, offer=offer, cached_at=cached_at)

    def set(
        self,
        ean: str,
        market: str,
        provider: str,
        max_delivery_days: int,
        offer: OfferResult | None,
    ) -> None:
        cached_at = time.time()
        if offer is None:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO price_cache
                    (ean, market, provider, max_delivery_days, found, cached_at)
                VALUES (?, ?, ?, ?, 0, ?)
                """,
                (ean, market, provider, max_delivery_days, cached_at),
            )
        else:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO price_cache
                    (ean, market, provider, max_delivery_days, found, price, currency,
                     seller, source_url, delivery_days, confidence, citations,
                     raw_response, cached_at)
                VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ean, market, provider, max_delivery_days,
                    str(offer.price), offer.currency, offer.seller, offer.source_url,
                    offer.delivery_days, offer.confidence,
                    json.dumps(list(offer.citations)), offer.raw_response, cached_at,
                ),
            )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
```

```python
# backend/tests/cache/__init__.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/cache/test_sqlite_cache.py -v`
Expected: PASS (5 tests — after removing the placeholder from Step 1)

- [ ] **Step 5: Commit**

```bash
git add backend/app/cache/__init__.py backend/app/cache/sqlite_cache.py backend/tests/cache/__init__.py backend/tests/cache/test_sqlite_cache.py
git commit -m "Add SQLite price cache keyed on (ean, market, provider, max_delivery_days)"
```

---

## Task 4: `PerplexityProvider`

**Files:**
- Create: `backend/app/providers/perplexity.py`
- Test: `backend/tests/providers/test_perplexity.py`

**Interfaces:**
- Consumes: `OfferResult`/`PriceProvider` from Task 1, `Product` from `app.models.product`.
- Produces: `PerplexityProvider` class with `name = "perplexity"` and
  `__init__(self, api_key: str, client: httpx.Client | None = None, timeout: float = 30.0)`,
  implementing `find_cheapest(self, product, market, max_delivery_days) -> OfferResult | None`.
  Used by Task 5's `lookup.py` and Task 6's live smoke test.
- This task uses a **fake httpx client** injected via the `client` constructor param — no real
  network call happens in this task's tests. The fake only needs to support `.post(url, headers=, json=)`
  returning an object with `.raise_for_status()` and `.json()`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/providers/test_perplexity.py
import json
from decimal import Decimal

import pytest

from app.models.product import Product
from app.providers.perplexity import PerplexityProvider


def _make_product(**overrides) -> Product:
    defaults = dict(
        tenant_id="t1", source="csv", external_id="1", variant_id=None,
        name="Test Product", ean="5901234123457",
        wholesale_price=Decimal("60.00"), currency="PLN", category="Test",
    )
    defaults.update(overrides)
    return Product(**defaults)


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, content: dict | None, citations: list[str] | None = None):
        self._content = content
        self._citations = citations or []
        self.last_request: dict | None = None

    def post(self, url, headers, json):
        self.last_request = {"url": url, "headers": headers, "json": json}
        return _FakeResponse(
            {
                "choices": [{"message": {"content": __import__("json").dumps(self._content)}}],
                "citations": self._citations,
            }
        )


def test_returns_offer_for_a_valid_found_response():
    client = _FakeClient(
        content={
            "found": True,
            "price": 89.99,
            "currency": "PLN",
            "seller": "Example Shop",
            "source_url": "https://example.com/product",
            "delivery_days": 2,
            "confidence": 0.85,
        },
        citations=["https://example.com/product"],
    )
    provider = PerplexityProvider(api_key="test-key", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer is not None
    assert offer.price == Decimal("89.99")
    assert offer.currency == "PLN"
    assert offer.seller == "Example Shop"
    assert offer.source_url == "https://example.com/product"
    assert offer.delivery_days == 2
    assert offer.confidence == 0.85
    assert offer.citations == ("https://example.com/product",)
    assert json.loads(offer.raw_response)["citations"] == ["https://example.com/product"]


def test_sends_bearer_auth_and_json_schema_response_format():
    client = _FakeClient(content={"found": False})
    provider = PerplexityProvider(api_key="secret-key", client=client)

    provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert client.last_request["headers"]["Authorization"] == "Bearer secret-key"
    assert client.last_request["json"]["response_format"]["type"] == "json_schema"
    assert client.last_request["json"]["model"] == "sonar"


def test_returns_none_when_not_found():
    client = _FakeClient(content={"found": False})
    provider = PerplexityProvider(api_key="test-key", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer is None


def test_returns_none_when_source_url_missing():
    client = _FakeClient(
        content={
            "found": True, "price": 10.0, "currency": "PLN", "seller": "X",
            "source_url": "", "delivery_days": 2, "confidence": 0.9,
        }
    )
    provider = PerplexityProvider(api_key="test-key", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer is None


def test_returns_none_when_delivery_exceeds_limit():
    client = _FakeClient(
        content={
            "found": True, "price": 10.0, "currency": "PLN", "seller": "X",
            "source_url": "https://example.com/x", "delivery_days": 20, "confidence": 0.9,
        }
    )
    provider = PerplexityProvider(api_key="test-key", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer is None


def test_returns_none_on_malformed_content():
    client = _FakeClient(content=None)  # json.dumps(None) -> "null" -> parses to None, not a dict
    provider = PerplexityProvider(api_key="test-key", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/providers/test_perplexity.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.providers.perplexity'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/providers/perplexity.py
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.models.product import Product
from app.providers.base import OfferResult

API_URL = "https://api.perplexity.ai/chat/completions"
MODEL = "sonar"

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


class PerplexityProvider:
    name = "perplexity"

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
        response = self._client.post(
            API_URL,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": [
                    {"role": "user", "content": self._build_prompt(product, market, max_delivery_days)}
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "cheapest_offer", "schema": RESPONSE_SCHEMA},
                },
            },
        )
        response.raise_for_status()
        return self._parse_response(response.json(), max_delivery_days)

    def _build_prompt(self, product: Product, market: str, max_delivery_days: int) -> str:
        ean_part = f" (EAN: {product.ean})" if product.ean else ""
        return (
            f'Find the cheapest real, currently-buyable offer for the product '
            f'"{product.name}"{ean_part} in the {market} market. '
            f"Only consider sellers that can deliver within {max_delivery_days} days — "
            f'if no such offer exists, set "found" to false rather than guessing. '
            f"Respond using the exact JSON schema requested, with the real source URL "
            f"you found the offer at."
        )

    def _parse_response(
        self, response_json: dict[str, Any], max_delivery_days: int
    ) -> OfferResult | None:
        raw_response = json.dumps(response_json)
        try:
            content = response_json["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            return None

        if not isinstance(parsed, dict) or not parsed.get("found"):
            return None

        source_url = parsed.get("source_url")
        if not source_url:
            return None

        delivery_days = parsed.get("delivery_days")
        if not isinstance(delivery_days, int) or delivery_days > max_delivery_days:
            return None

        try:
            price = Decimal(str(parsed["price"]))
        except (InvalidOperation, KeyError, TypeError):
            return None

        citations = tuple(response_json.get("citations", []))

        return OfferResult(
            price=price,
            currency=parsed.get("currency", "PLN"),
            seller=parsed.get("seller", "unknown"),
            source_url=source_url,
            delivery_days=delivery_days,
            confidence=float(parsed.get("confidence", 0.0)),
            citations=citations,
            raw_response=raw_response,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/providers/test_perplexity.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/providers/perplexity.py backend/tests/providers/test_perplexity.py
git commit -m "Add PerplexityProvider with structured JSON output parsing"
```

---

## Task 5: Cached lookup orchestration

**Files:**
- Create: `backend/app/providers/lookup.py`
- Test: `backend/tests/providers/test_lookup.py`

**Interfaces:**
- Consumes: `PriceProvider`/`OfferResult` (Task 1), `PriceCache` (Task 3).
- Produces: `get_offer_cached(product: Product, market: str, max_delivery_days: int, cache: PriceCache, provider: PriceProvider) -> OfferResult | None` —
  checks the cache first; on miss, calls `provider.find_cheapest(...)`, stores the result
  (hit or negative) in the cache, then returns it. Products without an `ean` are never cached
  (the cache key requires one) and always call the provider directly. This is the function
  Phase 4's job engine will call per product.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/providers/test_lookup.py
from decimal import Decimal

from app.cache.sqlite_cache import PriceCache
from app.models.product import Product
from app.providers.base import OfferResult
from app.providers.lookup import get_offer_cached


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


class _CountingProvider:
    name = "perplexity"

    def __init__(self, result: OfferResult | None):
        self._result = result
        self.call_count = 0

    def find_cheapest(self, product, market, max_delivery_days):
        self.call_count += 1
        return self._result


def test_calls_provider_and_caches_on_miss(tmp_path):
    cache = PriceCache(tmp_path / "cache.sqlite3")
    offer = _make_offer()
    provider = _CountingProvider(offer)
    product = _make_product()

    result = get_offer_cached(product, "PL", 5, cache, provider)

    assert result == offer
    assert provider.call_count == 1

    cached = cache.get(product.ean, "PL", "perplexity", 5)
    assert cached is not None
    assert cached.offer == offer
    cache.close()


def test_second_lookup_hits_cache_not_provider(tmp_path):
    cache = PriceCache(tmp_path / "cache.sqlite3")
    provider = _CountingProvider(_make_offer())
    product = _make_product()

    get_offer_cached(product, "PL", 5, cache, provider)
    result = get_offer_cached(product, "PL", 5, cache, provider)

    assert result == _make_offer()
    assert provider.call_count == 1  # second call was a cache hit
    cache.close()


def test_negative_result_is_cached_too(tmp_path):
    cache = PriceCache(tmp_path / "cache.sqlite3")
    provider = _CountingProvider(None)
    product = _make_product()

    first = get_offer_cached(product, "PL", 5, cache, provider)
    second = get_offer_cached(product, "PL", 5, cache, provider)

    assert first is None
    assert second is None
    assert provider.call_count == 1  # second call was a cached negative
    cache.close()


def test_product_without_ean_always_calls_provider(tmp_path):
    cache = PriceCache(tmp_path / "cache.sqlite3")
    provider = _CountingProvider(_make_offer())
    product = _make_product(ean=None)

    get_offer_cached(product, "PL", 5, cache, provider)
    get_offer_cached(product, "PL", 5, cache, provider)

    assert provider.call_count == 2  # never cached, no EAN to key on
    cache.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/providers/test_lookup.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.providers.lookup'`

- [ ] **Step 3: Write minimal implementation**

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

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/providers/test_lookup.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/providers/lookup.py backend/tests/providers/test_lookup.py
git commit -m "Add cached lookup orchestration gluing PriceCache and PriceProvider"
```

---

## Task 6: Opt-in real-API smoke test

**Files:**
- Test: `backend/tests/providers/test_perplexity_live.py`

**Interfaces:**
- Consumes: `PerplexityProvider` (Task 4), `Product` model. No new production code.

This mirrors the Phase 0-2 pattern used for `real_catalog.csv` (Task 10 of the prior plan): a
test that is skipped cleanly when its prerequisite isn't present, and only runs when the
developer explicitly opts in — here, by exporting `PERPLEXITY_API_KEY`. It makes exactly one
real HTTP call, verifying the end-to-end contract (a real Sonar response parses into a valid
`OfferResult` or a clean `None`), not a specific price.

- [ ] **Step 1: Write the test**

```python
# backend/tests/providers/test_perplexity_live.py
import os
from decimal import Decimal

import pytest

from app.models.product import Product
from app.providers.perplexity import PerplexityProvider

pytestmark = pytest.mark.skipif(
    not os.environ.get("PERPLEXITY_API_KEY"),
    reason="PERPLEXITY_API_KEY not set — export it to run this opt-in, cost-incurring smoke test",
)


def test_find_cheapest_returns_a_contract_valid_result_or_none():
    provider = PerplexityProvider(api_key=os.environ["PERPLEXITY_API_KEY"])
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

- [ ] **Step 2: Run it without the env var set, confirm it skips**

Run: `cd backend && pytest tests/providers/test_perplexity_live.py -v`
Expected: `1 skipped` — confirms the test never silently burns tokens in normal runs (CI, other
developers, this project's own default `pytest` invocation).

- [ ] **Step 3: Run it for real, with the key exported**

Run: `cd backend && PERPLEXITY_API_KEY=<your-key> pytest tests/providers/test_perplexity_live.py -v -s`
Expected: PASS. If it fails, the failure tells you something real about the contract (e.g. the
Sonar response shape drifted, or `response_format` was rejected) — do not loosen the assertions
to make it pass; fix `_parse_response` in `perplexity.py` instead, per Task 4.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/providers/test_perplexity_live.py
git commit -m "Add opt-in real-API smoke test for PerplexityProvider"
```

---

## Self-Review Notes

- **Spec coverage:** "Provider layer + Perplexity + Cache" (spec phase 3) — covered by Tasks 1–5.
  "Kontrakt providera" (`OfferResult` fields) — Task 1. "Polityka żadnych zmyślonych cen" (required
  `source_url`, `confidence`, anomaly detection, `raw_response` for audit) — Tasks 1, 2, 4. "Cache
  klucz (ean, market, provider, max_delivery_days), nigdy nie płacimy dwa razy" — Tasks 3, 5
  (negative-result caching is what makes the "never pay twice" guarantee hold on repeat scans).
  Deliberately **not** covered here (belongs to later phases per the spec's own phase ordering):
  cost/time estimation shown before a scan starts (Phase 4, needs the job engine's product count),
  sampling mode (Phase 4/5), `.claude/rules/` and `.claude/skills/` for providers (spec phase 7,
  meta-step, written last once the real contract has been built and battle-tested).
- **Placeholder scan:** none — every step has real code.
- **Type consistency:** `OfferResult` fields (Task 1) are used identically in `anomaly.py` (Task 2),
  `sqlite_cache.py` (Task 3), `perplexity.py` (Task 4), and `lookup.py` (Task 5). `PriceProvider.name`
  (Task 1) is what `lookup.py` (Task 5) uses as the cache key's `provider` dimension, and matches
  `PerplexityProvider.name = "perplexity"` (Task 4).

## Next steps after this plan

Phase 4 (job engine): async, resumable, concurrency-limited scan runner that calls
`get_offer_cached()` per product, streams progress, and computes the pre-scan cost/time estimate
(query count after subtracting cache hits × cost-per-query) — the estimate needs this phase's
cache to already exist, which is why it was deferred here rather than built twice.
