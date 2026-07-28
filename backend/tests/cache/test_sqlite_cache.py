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
