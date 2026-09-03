from __future__ import annotations

import asyncio

from app.cache.sqlite_cache import PriceCache
from app.providers.base import PriceProvider, ProviderAuthError, ProviderRateLimited, ProviderUnavailable
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
    # FallbackProvider's rate-limit latch is scoped to "one run" by design
    # (see its class docstring) but a provider instance built by
    # app.scans.api.get_provider() is a process-wide singleton reused across
    # every scan. Without this reset, one rate limit anywhere would silently
    # and permanently shift every later scan onto the costlier secondary for
    # the rest of the process's uptime. Providers that don't have this
    # concept (everything except FallbackProvider) simply don't define
    # reset(), so this is a no-op for them.
    reset = getattr(provider, "reset", None)
    if reset is not None:
        reset()

    store.start_scan(scan_id)
    pending = store.list_pending(scan_id)
    semaphore = asyncio.Semaphore(max_concurrency)
    stop_dispatch = asyncio.Event()
    rate_limit_hit = False

    async def process(record) -> None:
        nonlocal rate_limit_hit
        async with semaphore:
            if stop_dispatch.is_set():
                # Budget already known exhausted (rate limit) or the
                # provider's key already known bad (auth error) by another
                # in-flight call; leave this record pending rather than
                # making a call we already know will fail identically.
                return
            try:
                offer = await asyncio.to_thread(
                    get_offer_cached, record.product, market, max_delivery_days, cache, provider
                )
            except ProviderRateLimited:
                rate_limit_hit = True
                stop_dispatch.set()
                return
            except ProviderAuthError:
                # Not transient — retrying every remaining product would
                # waste the scan's full time budget on a failure the first
                # response already fully diagnosed. Leave pending; the scan
                # finalizes as FAILED below since some rows stay pending.
                stop_dispatch.set()
                return
            except ProviderUnavailable:
                # Leave it pending — a later run_scan() call for this scan_id
                # (process restart, or a retry) will pick it up again.
                return
            store.mark_done(record.id, offer)

    await asyncio.gather(*(process(record) for record in pending))

    if rate_limit_hit:
        store.pause_scan(scan_id)
    else:
        store.finalize_scan(scan_id)
