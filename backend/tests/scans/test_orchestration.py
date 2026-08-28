from decimal import Decimal

import pytest

from app.cache.sqlite_cache import PriceCache
from app.providers.base import OfferResult, ProviderProfile
from app.scans.models import ScanStatus
from app.scans.orchestration import create_scan
from app.scans.store import ScanStore
from app.sources.csv_source import CsvCatalogSource

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


class _FakeProvider:
    name = "perplexity"
    profile = ProviderProfile(cost_per_query_usd=Decimal("0.010"), seconds_per_query=2.5)


def test_create_scan_full_scope_persists_all_products_and_estimates_cost(tmp_path):
    store = ScanStore(tmp_path / "app.sqlite3")
    cache = PriceCache(tmp_path / "app.sqlite3")

    scan_id, warnings = create_scan(
        source=CsvCatalogSource(CSV_BYTES, tenant_id="t1"), scope_type="full",
        sample_per_category=None, sample_seed=1, market="PL", max_delivery_days=5,
        max_concurrency=5, staleness_threshold_days=14, store=store, cache=cache,
        provider=_FakeProvider(),
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

    scan_id, warnings = create_scan(
        source=CsvCatalogSource(CSV_BYTES, tenant_id="t1"), scope_type="full",
        sample_per_category=None, sample_seed=1, market="PL", max_delivery_days=5,
        max_concurrency=5, staleness_threshold_days=14, store=store, cache=cache,
        provider=_FakeProvider(),
    )

    scan = store.get_scan(scan_id)
    # One product already has a fresh cache entry -> only 1 real query needed.
    assert scan.estimate.queries_without_refresh == 1
    # The overlap itself (Task 6's StalenessReport) must be persisted and
    # readable back, not just used internally to compute the cost estimate.
    assert scan.overlapping_count == 1
    assert scan.stale_count == 0
    store.close()
    cache.close()


def test_create_scan_sample_scope_applies_water_filling(tmp_path):
    store = ScanStore(tmp_path / "app.sqlite3")
    cache = PriceCache(tmp_path / "app.sqlite3")

    scan_id, warnings = create_scan(
        source=CsvCatalogSource(CSV_BYTES, tenant_id="t1"), scope_type="sample",
        sample_per_category=1, sample_seed=1, market="PL", max_delivery_days=5,
        max_concurrency=5, staleness_threshold_days=14, store=store, cache=cache,
        provider=_FakeProvider(),
    )

    scan = store.get_scan(scan_id)
    # Both categories ("Elektronika", "Dom") have exactly 1 product each, and
    # the target is 1 per category -> both are fully included either way.
    assert scan.total_products == 2
    store.close()
    cache.close()


def test_create_scan_sample_scope_without_sample_per_category_raises(tmp_path):
    # Defense in depth: the API layer validates this before calling
    # create_scan, but orchestration.py must not silently rely on an `assert`
    # (stripped under `python -O`) in case it's ever called from elsewhere.
    store = ScanStore(tmp_path / "app.sqlite3")
    cache = PriceCache(tmp_path / "app.sqlite3")

    with pytest.raises(ValueError):
        create_scan(
            source=CsvCatalogSource(CSV_BYTES, tenant_id="t1"), scope_type="sample",
            sample_per_category=None, sample_seed=1, market="PL", max_delivery_days=5,
            max_concurrency=5, staleness_threshold_days=14, store=store, cache=cache,
            provider=_FakeProvider(),
        )
    store.close()
    cache.close()


def test_create_scan_surfaces_csv_parse_warnings(tmp_path):
    # A CSV row with a duplicate EAN gets dropped by CsvCatalogSource, and the
    # reason must be surfaced back to the caller -- not silently discarded --
    # so the user can learn why a row vanished from their upload.
    store = ScanStore(tmp_path / "app.sqlite3")
    cache = PriceCache(tmp_path / "app.sqlite3")
    csv_bytes = (
        "nazwa;cena;ean;kategoria\n"
        "Produkt A;10,00;5901234123457;Elektronika\n"
        "Produkt A dup;5,00;5901234123457;Elektronika\n"
    ).encode("utf-8")

    scan_id, warnings = create_scan(
        source=CsvCatalogSource(csv_bytes, tenant_id="t1"), scope_type="full",
        sample_per_category=None, sample_seed=1, market="PL", max_delivery_days=5,
        max_concurrency=5, staleness_threshold_days=14, store=store, cache=cache,
        provider=_FakeProvider(),
    )

    assert len(warnings) == 1
    assert "duplicate EAN" in warnings[0]
    store.close()
    cache.close()
