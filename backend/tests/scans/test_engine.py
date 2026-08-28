import asyncio
import time
from decimal import Decimal

import pytest

from app.cache.sqlite_cache import PriceCache
from app.models.product import Product
from app.providers.base import (
    OfferResult,
    ProviderAuthError,
    ProviderProfile,
    ProviderRateLimited,
    ProviderUnavailable,
)
from app.scans.engine import run_scan
from app.scans.estimate import estimate_cost
from app.scans.models import ProductStatus, ScanStatus
from app.scans.store import ScanStore

PROFILE = ProviderProfile(cost_per_query_usd=Decimal("0.010"), seconds_per_query=2.5)


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
            # Simulate real work so overlapping asyncio.to_thread workers
            # actually have a chance to coexist — without this delay, calls
            # complete so fast that genuine concurrency rarely materializes,
            # and this test would pass even with the semaphore removed.
            time.sleep(0.01)
            outcome = self._script[product.ean]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        finally:
            self._in_flight -= 1


def _make_store_with_products(tmp_path, products, *, max_concurrency=5):
    store = ScanStore(tmp_path / "app.sqlite3")
    estimate = estimate_cost(
        cache_misses=len(products), stale_count=0, max_concurrency=max_concurrency, profile=PROFILE
    )
    scan_id = store.create_scan(
        scope_type="full", sample_per_category=None, market="PL", max_delivery_days=5,
        max_concurrency=max_concurrency, staleness_threshold_days=14,
        products=products, stale_eans=(), estimate=estimate,
        overlapping_count=0, stale_count=0,
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
