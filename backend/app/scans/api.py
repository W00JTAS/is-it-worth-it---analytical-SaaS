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
from app.sources.column_mapping import ColumnMapping, ColumnMappingError
from app.sources.csv_preview import CsvPreview, build_csv_preview
from app.sources.csv_source import EmptyCsvError

logger = logging.getLogger(__name__)

router = APIRouter()

VALID_SCOPE_TYPES = ("full", "sample")

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "app.sqlite3"
_shared_store: ScanStore | None = None
_shared_cache: PriceCache | None = None
_shared_provider: PriceProvider | None = None

# Scan ids with a `run_scan` background task currently in flight in THIS
# process. Guards against a second `POST /scans/{id}/start` dispatching a
# duplicate `run_scan` coroutine while the first is still running -- which
# would double real provider calls and double effective concurrency against
# the rate-limited API. Deliberately in-memory and per-process: a genuine
# process restart starts with an empty set, which is correct, since
# resumability is exactly "no worker is currently running, so start one".
_scans_in_flight: set[str] = set()

# Bounds how long GET /scans/{id}/events will poll a scan that is never
# started: after this many ticks at SSE_POLL_INTERVAL_SECONDS with no
# transition out of "estimated", the stream sends a final event and closes
# instead of polling forever.
SSE_MAX_ESTIMATED_TICKS = 100
SSE_POLL_INTERVAL_SECONDS = 0.3


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
        "overlapping_count": scan.overlapping_count,
        "stale_count": scan.stale_count,
    }


def _csv_preview_to_dict(preview: CsvPreview) -> dict:
    return {
        "headers": preview.headers,
        "mapping": {
            "name": preview.mapping.name,
            "wholesale_price": preview.mapping.wholesale_price,
            "ean": preview.mapping.ean,
            "category": preview.mapping.category,
            "sku": preview.mapping.sku,
        },
        "sample_rows": preview.sample_rows,
        "total_rows": preview.total_rows,
        "parsed_count": preview.parsed_count,
        "warnings": preview.warnings,
        "warning_count": preview.warning_count,
    }


def _column_mapping_from_form(
    name_column: str | None,
    wholesale_price_column: str | None,
    ean_column: str | None,
    category_column: str | None,
    sku_column: str | None,
) -> ColumnMapping | None:
    required = (name_column, wholesale_price_column, ean_column, category_column)
    provided = [f for f in required if f is not None]
    if not provided:
        return None
    if len(provided) != len(required):
        raise HTTPException(
            status_code=400,
            detail=(
                "provide all of name_column/wholesale_price_column/ean_column/"
                "category_column, or none"
            ),
        )
    return ColumnMapping(
        name=name_column, wholesale_price=wholesale_price_column,
        ean=ean_column, category=category_column, sku=sku_column,
    )


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

    Also removes `scan_id` from `_scans_in_flight` in a `finally` block, so
    the duplicate-dispatch guard is cleared whether the run succeeds, fails,
    or this wrapper's own crash-recovery path runs.
    """
    try:
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
    finally:
        _scans_in_flight.discard(scan_id)


@router.post("/csv/preview")
async def post_csv_preview(
    file: UploadFile,
    name_column: str | None = Form(None),
    wholesale_price_column: str | None = Form(None),
    ean_column: str | None = Form(None),
    category_column: str | None = Form(None),
    sku_column: str | None = Form(None),
):
    mapping = _column_mapping_from_form(
        name_column, wholesale_price_column, ean_column, category_column, sku_column,
    )
    csv_bytes = await file.read()
    try:
        preview = build_csv_preview(csv_bytes, tenant_id="default", mapping_override=mapping)
    except EmptyCsvError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _csv_preview_to_dict(preview)


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
    if max_concurrency < 1:
        raise HTTPException(
            status_code=400, detail=f"max_concurrency must be >= 1, got {max_concurrency!r}"
        )
    if max_delivery_days < 1:
        raise HTTPException(
            status_code=400, detail=f"max_delivery_days must be >= 1, got {max_delivery_days!r}"
        )
    if staleness_threshold_days < 0:
        raise HTTPException(
            status_code=400,
            detail=f"staleness_threshold_days must be >= 0, got {staleness_threshold_days!r}",
        )
    if scope_type == "sample" and (sample_per_category is None or sample_per_category < 1):
        raise HTTPException(
            status_code=400,
            detail="sample_per_category must be >= 1 when scope_type is 'sample'",
        )

    csv_bytes = await file.read()
    try:
        scan_id, warnings = create_scan(
            csv_bytes=csv_bytes, tenant_id="default", scope_type=scope_type,
            sample_per_category=sample_per_category, sample_seed=_sample_seed_from_csv(csv_bytes),
            market=market, max_delivery_days=max_delivery_days, max_concurrency=max_concurrency,
            staleness_threshold_days=staleness_threshold_days,
            store=store, cache=cache, provider_name=provider.name,
        )
    except (EmptyCsvError, ColumnMappingError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    scan = store.get_scan(scan_id)
    result = _scan_to_dict(scan)
    result["warnings"] = warnings
    return result


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

    if scan_id in _scans_in_flight:
        raise HTTPException(status_code=409, detail="scan already running")
    _scans_in_flight.add(scan_id)

    # Set the DB status synchronously, before dispatching the background
    # task, not inside run_scan (which only executes after this response is
    # sent). Otherwise there's a window where this response says "running"
    # but the DB still says "estimated", and a crash in that window loses the
    # fact that a start was requested.
    store.start_scan(scan_id)

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
        estimated_ticks = 0
        while True:
            scan = store.get_scan(scan_id)
            yield f"data: {json.dumps(_scan_to_dict(scan))}\n\n"
            if scan.status.value in ("done", "failed"):
                break
            if scan.status.value == "estimated":
                estimated_ticks += 1
                if estimated_ticks >= SSE_MAX_ESTIMATED_TICKS:
                    # Never started -- stop polling forever and tell the
                    # client explicitly rather than leaving the connection
                    # open indefinitely.
                    yield (
                        "data: "
                        + json.dumps({"scan_id": scan_id, "status": "timeout",
                                       "detail": "scan was never started"})
                        + "\n\n"
                    )
                    break
            else:
                estimated_ticks = 0
            await asyncio.sleep(SSE_POLL_INTERVAL_SECONDS)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
