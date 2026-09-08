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
from app.sources.base import CatalogSource
from app.sources.column_mapping import ColumnMapping, ColumnMappingError
from app.sources.csv_preview import CsvPreview, build_csv_preview
from app.sources.csv_source import CsvCatalogSource, EmptyCsvError
from app.sources.shopify_source import ShopifyApiError, ShopifyCatalogSource
from app.sources.woo_source import WooCommerceApiError, WooCommerceCatalogSource

logger = logging.getLogger(__name__)

router = APIRouter()

VALID_SCOPE_TYPES = ("full", "sample")
VALID_SOURCE_TYPES = ("csv", "shopify", "woocommerce")

# Mirrors csv_preview.py's WARNING_LIMIT: a blank-titled Shopify product with
# many variants now emits one "missing name, skipped" warning per variant
# (see shopify_source.py), which could otherwise grow unbounded into this
# JSON response.
WARNING_LIMIT = 20

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
        provider_name = os.environ.get("PROVIDER", "perplexity")
        if provider_name == "groq":
            from app.providers.groq import GroqProvider
            _shared_provider = GroqProvider(api_key=os.environ["GROQ_API_KEY"])
        elif provider_name == "groq+firecrawl":
            # Same composition as scripts/provider_eval.py's build_provider:
            # GroqProvider primary (free, quota-constrained), FirecrawlProvider
            # secondary (paid). FallbackProvider's latch switches to secondary
            # after primary's first ProviderRateLimited -- NOT fully
            # quota-independent, though: FirecrawlProvider._extract shares
            # Groq's own extraction-model budget (gpt-oss-20b), only its
            # SEARCH step avoids Groq entirely. This is the only combination
            # with a measured found-rate: 32-84% across several prompt-tuning
            # rounds on the tuning sample, 64% raw (89% among completed
            # lookups) on a fresh hold-out sample -- plain "groq" alone was
            # measured at 8-25% before FallbackProvider existed.
            # run_scan() resets the latch at the start of every scan (see
            # engine.py) since this provider is a process-wide singleton
            # (below), not a fresh instance per run like provider_eval.py's.
            from app.providers.fallback import FallbackProvider
            from app.providers.firecrawl import FirecrawlProvider
            from app.providers.groq import GroqProvider
            primary = GroqProvider(api_key=os.environ["GROQ_API_KEY"])
            secondary = FirecrawlProvider(
                api_key=os.environ["FIRECRAWL_API_KEY"],
                groq_api_key=os.environ["GROQ_API_KEY"],
            )
            _shared_provider = FallbackProvider(primary, secondary)
        else:
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
    provided = [f for f in required if f]
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


def _partial_column_mapping_from_form(
    name_column: str | None,
    wholesale_price_column: str | None,
    ean_column: str | None,
    category_column: str | None,
    sku_column: str | None,
) -> ColumnMapping | None:
    """Permissive counterpart to `_column_mapping_from_form`, used only by
    `POST /csv/preview`.

    Unlike the strict helper, this accepts ANY subset of the 4 required
    fields -- including zero, a partial subset, or all 4 -- and never raises.
    A blank/falsy value for a given field is treated as "not provided" for
    that field (matching the truthy-check fix applied to the strict helper
    above), so it falls back to auto-detection via `build_csv_preview`'s
    `_merge_mapping`. Only when ALL 5 arguments are falsy do we return
    `None` outright, letting `build_csv_preview` auto-detect everything.
    """
    fields = (name_column, wholesale_price_column, ean_column, category_column, sku_column)
    if not any(fields):
        return None
    return ColumnMapping(
        name=name_column or None,
        wholesale_price=wholesale_price_column or None,
        ean=ean_column or None,
        category=category_column or None,
        sku=sku_column or None,
    )


def _sample_seed(seed_material: bytes) -> int:
    # Deterministic per-request seed derived from stable identifying bytes of
    # the source being scanned (the uploaded file's content for CSV, the
    # store's own domain/URL for Shopify/WooCommerce), so repeating the same
    # request samples the same products; not security-sensitive, just needs
    # to be stable and content-dependent.
    return int(hashlib.sha256(seed_material).hexdigest()[:8], 16)


def _build_source(
    source_type: str,
    tenant_id: str,
    csv_bytes: bytes | None,
    column_mapping: ColumnMapping | None,
    shop_domain: str | None,
    access_token: str | None,
    store_url: str | None,
    consumer_key: str | None,
    consumer_secret: str | None,
) -> tuple[CatalogSource, int]:
    """Builds the `CatalogSource` for `POST /scans` matching `source_type`,
    plus a `_sample_seed` derived from that source's own stable identifying
    bytes. Raises `HTTPException(400)` if the credentials `source_type`
    requires weren't provided -- mirrors `_column_mapping_from_form`'s
    all-required-or-400 pattern above.
    """
    if source_type == "csv":
        if csv_bytes is None:
            raise HTTPException(
                status_code=400, detail="file is required when source_type is 'csv'"
            )
        return (
            CsvCatalogSource(csv_bytes, tenant_id=tenant_id, column_mapping=column_mapping),
            _sample_seed(csv_bytes),
        )
    if source_type == "shopify":
        if not shop_domain or not access_token:
            raise HTTPException(
                status_code=400,
                detail="shop_domain and access_token are required when source_type is 'shopify'",
            )
        return (
            ShopifyCatalogSource(
                shop_domain=shop_domain, access_token=access_token, tenant_id=tenant_id,
            ),
            _sample_seed(shop_domain.encode()),
        )
    # source_type == "woocommerce" -- the only remaining member of
    # VALID_SOURCE_TYPES, already checked by the caller.
    if not store_url or not consumer_key or not consumer_secret:
        raise HTTPException(
            status_code=400,
            detail=(
                "store_url, consumer_key and consumer_secret are required when "
                "source_type is 'woocommerce'"
            ),
        )
    return (
        WooCommerceCatalogSource(
            store_url=store_url, consumer_key=consumer_key, consumer_secret=consumer_secret,
            tenant_id=tenant_id,
        ),
        # rstrip("/") to match WooCommerceCatalogSource's own normalization
        # (store_url.rstrip("/")), so two requests differing only by a
        # trailing slash sample the same products.
        _sample_seed(store_url.rstrip("/").encode()),
    )


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
    mapping = _partial_column_mapping_from_form(
        name_column, wholesale_price_column, ean_column, category_column, sku_column,
    )
    csv_bytes = await file.read()
    try:
        preview = await asyncio.to_thread(build_csv_preview, csv_bytes, "default", mapping)
    except EmptyCsvError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _csv_preview_to_dict(preview)


@router.post("/scans")
async def post_scans(
    file: UploadFile | None = None,
    source_type: str = Form("csv"),
    scope_type: str = Form(...),
    sample_per_category: int | None = Form(None),
    market: str = Form("PL"),
    max_delivery_days: int = Form(5),
    max_concurrency: int = Form(5),
    staleness_threshold_days: int = Form(14),
    name_column: str | None = Form(None),
    wholesale_price_column: str | None = Form(None),
    ean_column: str | None = Form(None),
    category_column: str | None = Form(None),
    sku_column: str | None = Form(None),
    shop_domain: str | None = Form(None),
    access_token: str | None = Form(None),
    store_url: str | None = Form(None),
    consumer_key: str | None = Form(None),
    consumer_secret: str | None = Form(None),
    store: ScanStore = Depends(get_store),
    cache: PriceCache = Depends(get_cache),
    provider: PriceProvider = Depends(get_provider),
):
    if source_type not in VALID_SOURCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"source_type must be one of {VALID_SOURCE_TYPES!r}, got {source_type!r}",
        )
    if source_type == "shopify":
        # ShopifyCatalogSource's GraphQL query requests far more than
        # Shopify's hard per-query cost cap (rejected by every real store,
        # every plan, before executing), and unlike WooCommerceCatalogSource
        # has no pagination cap or response-shape error handling. Gated here
        # until it's hardened to the same level.
        raise HTTPException(
            status_code=400,
            detail=(
                "source_type 'shopify' is not yet production-ready (GraphQL query cost "
                "exceeds Shopify's per-query limit for any real store; no pagination cap "
                "or response-shape error handling) -- pending a hardening pass matching "
                "WooCommerceCatalogSource. Use 'csv' or 'woocommerce' instead."
            ),
        )
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

    # Column mapping is a CSV-only concern; validating it for another
    # source_type would reject the request over a field that has nothing to
    # do with the actual (Shopify/WooCommerce) source being scanned.
    column_mapping = (
        _column_mapping_from_form(
            name_column, wholesale_price_column, ean_column, category_column, sku_column,
        )
        if source_type == "csv"
        else None
    )

    # Only read the upload into memory for source_type="csv" -- a leftover
    # `file` on a Shopify/WooCommerce request would otherwise be buffered
    # into a bytes object and discarded unused.
    csv_bytes = await file.read() if file is not None and source_type == "csv" else None
    source, sample_seed = _build_source(
        source_type, "default", csv_bytes, column_mapping,
        shop_domain, access_token, store_url, consumer_key, consumer_secret,
    )
    try:
        # Shopify/WooCommerce sources do blocking network I/O inside
        # fetch_products() (called from create_scan) -- offload to a thread
        # like post_csv_preview already does for build_csv_preview, so a
        # slow/large catalog fetch doesn't stall the event loop (and with it
        # every other concurrent request, including SSE progress polling).
        scan_id, warnings = await asyncio.to_thread(
            create_scan,
            source=source, scope_type=scope_type,
            sample_per_category=sample_per_category, sample_seed=sample_seed,
            market=market, max_delivery_days=max_delivery_days, max_concurrency=max_concurrency,
            staleness_threshold_days=staleness_threshold_days,
            store=store, cache=cache, provider=provider,
        )
    except (EmptyCsvError, ColumnMappingError, ShopifyApiError, WooCommerceApiError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    scan = store.get_scan(scan_id)
    result = _scan_to_dict(scan)
    result["warnings"] = warnings[:WARNING_LIMIT]
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
            if scan.status.value in ("done", "failed", "paused"):
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
