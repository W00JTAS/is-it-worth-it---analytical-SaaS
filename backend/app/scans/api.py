from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.cache.sqlite_cache import PriceCache
from app.providers.base import PriceProvider
from app.providers.perplexity import PerplexityProvider
from app.scans.engine import run_scan
from app.scans.orchestration import create_scan
from app.scans.store import ScanStore

logger = logging.getLogger(__name__)

router = APIRouter()

VALID_SCOPE_TYPES = ("full", "sample")

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "app.sqlite3"
_shared_store: ScanStore | None = None
_shared_cache: PriceCache | None = None
_shared_provider: PriceProvider | None = None


def get_store() -> ScanStore:
    global _shared_store
    if _shared_store is None:
        DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _shared_store = ScanStore(DEFAULT_DB_PATH)
    return _shared_store


def get_cache() -> PriceCache:
    global _shared_cache
    if _shared_cache is None:
        DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _shared_cache = PriceCache(DEFAULT_DB_PATH)
    return _shared_cache


def get_provider() -> PriceProvider:
    global _shared_provider
    if _shared_provider is None:
        import os
        _shared_provider = PerplexityProvider(api_key=os.environ["PERPLEXITY_API_KEY"])
    return _shared_provider


def _estimate_to_dict(estimate) -> dict:
    return {
        "queries_without_refresh": estimate.queries_without_refresh,
        "queries_with_refresh": estimate.queries_with_refresh,
        "cost_usd_without_refresh": str(estimate.cost_usd_without_refresh),
        "cost_usd_with_refresh": str(estimate.cost_usd_with_refresh),
        "seconds_without_refresh": estimate.seconds_without_refresh,
        "seconds_with_refresh": estimate.seconds_with_refresh,
    }


def _scan_to_dict(scan) -> dict:
    return {
        "scan_id": scan.id,
        "status": scan.status.value,
        "scope_type": scan.scope_type,
        "total_products": scan.total_products,
        "completed_products": scan.completed_products,
        "estimate": _estimate_to_dict(scan.estimate),
    }


def _sample_seed_from_csv(csv_bytes: bytes) -> int:
    # Deterministic per-upload seed derived from the file's actual content (not
    # just its length) so re-uploading the same file sample the same products;
    # not security-sensitive, just needs to be stable and content-dependent.
    return int(hashlib.sha256(csv_bytes).hexdigest()[:8], 16)


async def _run_scan_and_guard(
    scan_id: str,
    store: ScanStore,
    cache: PriceCache,
    provider: PriceProvider,
    market: str,
    max_delivery_days: int,
    max_concurrency: int,
) -> None:
    """Wraps `run_scan` for background-task dispatch.

    `run_scan` itself already handles `ProviderUnavailable` internally (leaves
    the affected products pending for a later retry) and never lets it
    escape. Anything that DOES escape here is therefore a genuine bug, not a
    transient failure. FastAPI's `BackgroundTasks` gives such an exception no
    visible home -- Starlette swallows/only-stderr-logs it, invisible to any
    API consumer -- and the scan would otherwise stay stuck in `running`
    forever since `store.finalize_scan` is never reached. So: log it loudly,
    then finalize the scan directly so at least the status reflects reality
    (finalize_scan already lands on FAILED when products are still pending).
    """
    try:
        await run_scan(scan_id, store, cache, provider, market, max_delivery_days, max_concurrency)
    except Exception:
        logger.exception(
            "run_scan crashed unexpectedly for scan_id=%s (genuine bug, not "
            "ProviderUnavailable); marking scan as failed",
            scan_id,
        )
        try:
            store.finalize_scan(scan_id)
        except Exception:
            logger.exception(
                "failed to finalize scan_id=%s after an earlier run_scan crash", scan_id
            )


@router.post("/scans")
async def post_scans(
    file: UploadFile,
    scope_type: str = Form(...),
    sample_per_category: int | None = Form(None),
    market: str = Form("PL"),
    max_delivery_days: int = Form(5),
    max_concurrency: int = Form(5),
    staleness_threshold_days: int = Form(14),
    store: ScanStore = Depends(get_store),
    cache: PriceCache = Depends(get_cache),
    provider: PriceProvider = Depends(get_provider),
):
    if scope_type not in VALID_SCOPE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"scope_type must be one of {VALID_SCOPE_TYPES!r}, got {scope_type!r}",
        )

    csv_bytes = await file.read()
    scan_id = create_scan(
        csv_bytes=csv_bytes, tenant_id="default", scope_type=scope_type,
        sample_per_category=sample_per_category, sample_seed=_sample_seed_from_csv(csv_bytes),
        market=market, max_delivery_days=max_delivery_days, max_concurrency=max_concurrency,
        staleness_threshold_days=staleness_threshold_days,
        store=store, cache=cache, provider_name=provider.name,
    )
    scan = store.get_scan(scan_id)
    return _scan_to_dict(scan)


class StartScanRequest(BaseModel):
    force_refresh_stale: bool


@router.post("/scans/{scan_id}/start")
async def start_scan(
    scan_id: str,
    body: StartScanRequest,
    background_tasks: BackgroundTasks,
    store: ScanStore = Depends(get_store),
    cache: PriceCache = Depends(get_cache),
    provider: PriceProvider = Depends(get_provider),
):
    scan = store.get_scan(scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="scan not found")

    if body.force_refresh_stale:
        for record in store.list_pending(scan_id):
            if record.was_stale and record.product.ean:
                cache.invalidate(record.product.ean, scan.market, provider.name, scan.max_delivery_days)

    background_tasks.add_task(
        _run_scan_and_guard,
        scan_id, store, cache, provider, scan.market, scan.max_delivery_days, scan.max_concurrency,
    )
    return {"status": "running"}


@router.get("/scans/{scan_id}")
async def get_scan_status(scan_id: str, store: ScanStore = Depends(get_store)):
    scan = store.get_scan(scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="scan not found")
    return _scan_to_dict(scan)


@router.get("/scans/{scan_id}/events")
async def stream_scan_events(scan_id: str, store: ScanStore = Depends(get_store)):
    scan = store.get_scan(scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="scan not found")

    async def event_generator():
        while True:
            scan = store.get_scan(scan_id)
            yield f"data: {json.dumps(_scan_to_dict(scan))}\n\n"
            if scan.status.value in ("done", "failed"):
                break
            await asyncio.sleep(0.3)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
