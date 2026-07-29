from __future__ import annotations

import asyncio

from app.cache.sqlite_cache import PriceCache
from app.providers.base import PriceProvider, ProviderUnavailable
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

    async def process(record) -> None:
        async with semaphore:
            try:
                offer = await asyncio.to_thread(
                    get_offer_cached, record.product, market, max_delivery_days, cache, provider
                )
            except ProviderUnavailable:
                # Leave it pending — a later run_scan() call for this scan_id
                # (process restart, or a retry) will pick it up again.
                return
            store.mark_done(record.id, offer)

    await asyncio.gather(*(process(record) for record in pending))
    store.finalize_scan(scan_id)
