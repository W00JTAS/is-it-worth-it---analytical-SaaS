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
