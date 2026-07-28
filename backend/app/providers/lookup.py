from __future__ import annotations

from app.cache.sqlite_cache import PriceCache
from app.models.product import Product
from app.providers.base import OfferResult, PriceProvider, ProviderUnavailable


def get_offer_cached(
    product: Product,
    market: str,
    max_delivery_days: int,
    cache: PriceCache,
    provider: PriceProvider,
) -> OfferResult | None:
    if not product.ean:
        try:
            return provider.find_cheapest(product, market, max_delivery_days)
        except ProviderUnavailable:
            return None

    cached = cache.get(product.ean, market, provider.name, max_delivery_days)
    if cached is not None:
        return cached.offer

    try:
        offer = provider.find_cheapest(product, market, max_delivery_days)
    except ProviderUnavailable:
        # Transient failure (network error, timeout, 429/5xx) — do NOT cache
        # this as a negative result, so the next scan retries it.
        return None
    cache.set(product.ean, market, provider.name, max_delivery_days, offer)
    return offer
