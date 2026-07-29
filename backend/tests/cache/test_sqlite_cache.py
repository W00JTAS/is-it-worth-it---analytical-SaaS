import threading
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


def test_get_and_set_work_from_a_different_thread(tmp_path):
    """The connection is created with check_same_thread=False (Phase 4 will run
    a concurrent job engine sharing one PriceCache across threads/tasks) — a
    get()/set() round trip from a non-constructor thread must not raise
    sqlite3's "objects created in a thread can only be used in that same
    thread" ProgrammingError."""
    cache = PriceCache(tmp_path / "cache.sqlite3")
    offer = _make_offer()
    errors: list[BaseException] = []

    def worker():
        try:
            cache.set("5901234123457", "PL", "perplexity", 5, offer)
            entry = cache.get("5901234123457", "PL", "perplexity", 5)
            assert entry is not None
            assert entry.found is True
            assert entry.offer == offer
        except BaseException as exc:  # noqa: BLE001 - surfaced via assertion below
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    assert not errors, errors
    # And a second, sequential get/set from the main thread still behaves.
    entry = cache.get("5901234123457", "PL", "perplexity", 5)
    assert entry is not None
    assert entry.offer == offer
    cache.close()


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
