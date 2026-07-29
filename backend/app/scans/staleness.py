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
    stale_eans: list[str] = []

    for product in products:
        if not product.ean:
            continue
        entry = cache.get(product.ean, market, provider_name, max_delivery_days)
        if entry is None:
            continue
        overlapping_count += 1
        if now - entry.cached_at > threshold_seconds:
            stale_eans.append(product.ean)

    return StalenessReport(
        overlapping_count=overlapping_count,
        stale_eans=tuple(stale_eans),
    )
