from decimal import Decimal

from app.cache.sqlite_cache import PriceCache
from app.models.product import Product
from app.providers.base import OfferResult, ProviderUnavailable
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


class _UnavailableProvider:
    """Simulates a transient failure (network error / 429 / 5xx) — see
    PerplexityProvider.find_cheapest, which raises ProviderUnavailable for these."""

    name = "perplexity"

    def __init__(self):
        self.call_count = 0

    def find_cheapest(self, product, market, max_delivery_days):
        self.call_count += 1
        raise ProviderUnavailable("simulated transient failure")


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


def test_provider_unavailable_returns_none_and_is_not_cached(tmp_path):
    """A transient failure (network error / 429 / 5xx) must not be persisted as
    a 30-day negative result — see final whole-branch review, Important 4."""
    cache = PriceCache(tmp_path / "cache.sqlite3")
    provider = _UnavailableProvider()
    product = _make_product()

    result = get_offer_cached(product, "PL", 5, cache, provider)

    assert result is None
    assert provider.call_count == 1
    # Nothing was written to the cache — a later lookup must retry, not reuse
    # a stale "not found" verdict from the transient failure.
    assert cache.get(product.ean, "PL", "perplexity", 5) is None

    # Confirm it genuinely retries (would be 1 forever if it had been cached).
    get_offer_cached(product, "PL", 5, cache, provider)
    assert provider.call_count == 2
    cache.close()


def test_provider_unavailable_is_swallowed_for_product_without_ean(tmp_path):
    cache = PriceCache(tmp_path / "cache.sqlite3")
    provider = _UnavailableProvider()
    product = _make_product(ean=None)

    result = get_offer_cached(product, "PL", 5, cache, provider)

    assert result is None
    assert provider.call_count == 1
    cache.close()
