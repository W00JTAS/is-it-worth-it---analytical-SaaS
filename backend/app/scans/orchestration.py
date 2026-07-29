from __future__ import annotations

from app.cache.sqlite_cache import PriceCache
from app.normalize.grouping import group_by_category
from app.scans.estimate import estimate_cost
from app.scans.sampling import resolve_sample_scope
from app.scans.staleness import analyze_staleness
from app.scans.store import ScanStore
from app.sources.csv_source import CsvCatalogSource


def create_scan(
    *,
    csv_bytes: bytes,
    tenant_id: str,
    scope_type: str,
    sample_per_category: int | None,
    sample_seed: int,
    market: str,
    max_delivery_days: int,
    max_concurrency: int,
    staleness_threshold_days: int,
    store: ScanStore,
    cache: PriceCache,
    provider_name: str,
) -> str:
    source = CsvCatalogSource(csv_bytes, tenant_id=tenant_id)
    all_products = source.fetch_products()

    if scope_type == "sample":
        assert sample_per_category is not None
        products_by_category = group_by_category(all_products)
        scoped_products = resolve_sample_scope(
            products_by_category, sample_per_category, sample_seed
        )
    else:
        scoped_products = all_products

    staleness = analyze_staleness(
        scoped_products, cache, market, provider_name, max_delivery_days,
        staleness_threshold_days,
    )

    cache_misses = sum(
        1 for p in scoped_products
        if p.ean is None or cache.get(p.ean, market, provider_name, max_delivery_days) is None
    )
    estimate = estimate_cost(
        cache_misses=cache_misses,
        stale_count=len(staleness.stale_external_ids),
        max_concurrency=max_concurrency,
    )

    return store.create_scan(
        scope_type=scope_type,
        sample_per_category=sample_per_category,
        market=market,
        max_delivery_days=max_delivery_days,
        max_concurrency=max_concurrency,
        staleness_threshold_days=staleness_threshold_days,
        products=scoped_products,
        stale_external_ids=staleness.stale_external_ids,
        estimate=estimate,
    )
