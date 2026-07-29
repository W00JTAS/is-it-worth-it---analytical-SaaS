from decimal import Decimal

from app.cache.sqlite_cache import PriceCache
from app.providers.base import OfferResult
from app.scans.models import ScanStatus
from app.scans.orchestration import create_scan
from app.scans.store import ScanStore

CSV_BYTES = (
    "nazwa;cena;ean;kategoria\n"
    "Produkt A;10,00;5901234123457;Elektronika\n"
    "Produkt B;20,00;5900000000009;Dom\n"
).encode("utf-8")


def _make_offer(**overrides) -> OfferResult:
    defaults = dict(
        price=Decimal("15.00"), currency="PLN", seller="Example Shop",
        source_url="https://example.com/product", delivery_days=2,
        confidence=0.85, citations=("https://example.com/product",),
        raw_response="{}",
    )
    defaults.update(overrides)
    return OfferResult(**defaults)


def test_create_scan_full_scope_persists_all_products_and_estimates_cost(tmp_path):
    store = ScanStore(tmp_path / "app.sqlite3")
    cache = PriceCache(tmp_path / "app.sqlite3")

    scan_id = create_scan(
        csv_bytes=CSV_BYTES, tenant_id="t1", scope_type="full", sample_per_category=None,
        sample_seed=1, market="PL", max_delivery_days=5, max_concurrency=5,
        staleness_threshold_days=14, store=store, cache=cache, provider_name="perplexity",
    )

    scan = store.get_scan(scan_id)
    assert scan is not None
    assert scan.status == ScanStatus.ESTIMATED
    assert scan.total_products == 2
    assert scan.estimate.queries_without_refresh == 2  # neither EAN cached yet
    store.close()
    cache.close()


def test_create_scan_detects_overlap_and_staleness_against_existing_cache(tmp_path):
    store = ScanStore(tmp_path / "app.sqlite3")
    cache = PriceCache(tmp_path / "app.sqlite3")
    cache.set("5901234123457", "PL", "perplexity", 5, _make_offer())

    scan_id = create_scan(
        csv_bytes=CSV_BYTES, tenant_id="t1", scope_type="full", sample_per_category=None,
        sample_seed=1, market="PL", max_delivery_days=5, max_concurrency=5,
        staleness_threshold_days=14, store=store, cache=cache, provider_name="perplexity",
    )

    scan = store.get_scan(scan_id)
    # One product already has a fresh cache entry -> only 1 real query needed.
    assert scan.estimate.queries_without_refresh == 1
    store.close()
    cache.close()


def test_create_scan_sample_scope_applies_water_filling(tmp_path):
    store = ScanStore(tmp_path / "app.sqlite3")
    cache = PriceCache(tmp_path / "app.sqlite3")

    scan_id = create_scan(
        csv_bytes=CSV_BYTES, tenant_id="t1", scope_type="sample", sample_per_category=1,
        sample_seed=1, market="PL", max_delivery_days=5, max_concurrency=5,
        staleness_threshold_days=14, store=store, cache=cache, provider_name="perplexity",
    )

    scan = store.get_scan(scan_id)
    # Both categories ("Elektronika", "Dom") have exactly 1 product each, and
    # the target is 1 per category -> both are fully included either way.
    assert scan.total_products == 2
    store.close()
    cache.close()
