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
