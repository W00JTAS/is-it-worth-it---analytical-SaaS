import asyncio
import io
import logging
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.background import BackgroundTasks

import app.scans.api as api_module
from app.cache.sqlite_cache import PriceCache
from app.providers.base import OfferResult
from app.scans.api import (
    StartScanRequest,
    _build_source,
    _scans_in_flight,
    get_cache,
    get_provider,
    get_store,
    router,
    start_scan,
)
from app.scans.store import ScanStore

CSV_BYTES = (
    "nazwa;cena;ean;kategoria\n"
    "Produkt A;10,00;5901234123457;Elektronika\n"
).encode("utf-8")


class _FakeProvider:
    name = "perplexity"

    def __init__(self):
        self.call_count = 0

    def find_cheapest(self, product, market, max_delivery_days):
        self.call_count += 1
        return OfferResult(
            price=Decimal("15.00"), currency="PLN",
            seller="Shop", source_url="https://example.com/x", delivery_days=2,
            confidence=0.9, citations=(), raw_response="{}",
        )


class _BuggyProvider:
    """Simulates a genuine bug in the provider (NOT ProviderUnavailable) so we
    can verify a crash inside run_scan's background task doesn't vanish
    silently and doesn't leave the scan stuck in RUNNING forever."""

    name = "perplexity"

    def find_cheapest(self, product, market, max_delivery_days):
        raise RuntimeError("boom: simulated genuine bug, not a transient failure")


def _make_app(tmp_path, provider=None):
    app = FastAPI()
    app.include_router(router)
    store = ScanStore(tmp_path / "app.sqlite3")
    cache = PriceCache(tmp_path / "app.sqlite3")
    provider = provider or _FakeProvider()
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_cache] = lambda: cache
    app.dependency_overrides[get_provider] = lambda: provider
    return app, store, cache


def test_post_scans_creates_an_estimated_scan_without_starting_it(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "full"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "estimated"
    assert body["total_products"] == 1
    assert "estimate" in body
    assert body["warnings"] == []
    assert store.get_scan(body["scan_id"]).status.value == "estimated"


def test_post_scans_response_includes_overlapping_and_stale_counts(tmp_path):
    # Task 6's StalenessReport (overlapping_count / stale_eans) must
    # reach the API response, not just be discarded after computing the cost
    # estimate. Pre-seed the cache so one product overlaps an existing entry.
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)
    cache.set(
        "5901234123457", "PL", "perplexity", 5,
        OfferResult(
            price=Decimal("15.00"), currency="PLN", seller="Shop",
            source_url="https://example.com/x", delivery_days=2,
            confidence=0.9, citations=(), raw_response="{}",
        ),
    )

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "full"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["overlapping_count"] == 1
    assert body["stale_count"] == 0


def test_get_scans_returns_404_for_unknown_id(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.get("/scans/does-not-exist")

    assert response.status_code == 404


def test_start_scan_runs_it_to_completion(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)
    scan_id = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "full"},
    ).json()["scan_id"]

    response = client.post(f"/scans/{scan_id}/start", json={"force_refresh_stale": False})

    assert response.status_code == 200
    final = client.get(f"/scans/{scan_id}").json()
    assert final["status"] == "done"
    assert final["completed_products"] == 1


def test_start_scan_returns_404_for_unknown_id(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post("/scans/does-not-exist/start", json={"force_refresh_stale": False})

    assert response.status_code == 404


# --- Carried-forward fix 1 (Task 8 review): reject invalid scope_type ------


def test_post_scans_rejects_invalid_scope_type(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "bogus"},
    )

    assert response.status_code == 400


def test_post_scans_accepts_sample_scope_type(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "sample", "sample_per_category": "1"},
    )

    assert response.status_code == 200


# --- Carried-forward fix 2 (Task 9 review): background task crash is not --
# --- silently invisible and doesn't leave the scan stuck forever ----------


def test_start_scan_marks_scan_failed_and_logs_when_run_scan_crashes_unexpectedly(
    tmp_path, caplog
):
    app, store, cache = _make_app(tmp_path, provider=_BuggyProvider())
    client = TestClient(app)
    scan_id = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "full"},
    ).json()["scan_id"]

    with caplog.at_level(logging.ERROR):
        response = client.post(f"/scans/{scan_id}/start", json={"force_refresh_stale": False})

    assert response.status_code == 200

    final = client.get(f"/scans/{scan_id}").json()
    # The genuine bug must not leave the scan stuck at "running"/"estimated"
    # forever with no trace -- it should be finalized (and, since the product
    # never completed, that finalization lands on "failed").
    assert final["status"] not in ("estimated", "running")
    assert final["status"] == "failed"

    # And the crash must be logged loudly, not swallowed silently.
    assert any("run_scan" in record.message or "boom" in record.message for record in caplog.records)


# --- Critical 1 (final whole-branch review): reject a duplicate start ------


def test_second_start_scan_call_is_rejected_while_first_is_in_flight(tmp_path):
    # TestClient runs background tasks synchronously after the response, so
    # two sequential client.post() calls can't naturally reproduce the race:
    # by the time the second request is made, the first's background task has
    # already finished. Instead, call the `start_scan` endpoint function
    # directly and control background-task execution ourselves, so we can
    # dispatch the first task, then attempt (and reject) a second dispatch
    # *before* the first has actually run.
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)
    provider = _FakeProvider()
    app.dependency_overrides[get_provider] = lambda: provider
    scan_id = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "full"},
    ).json()["scan_id"]

    async def scenario():
        body = StartScanRequest(force_refresh_stale=False)
        bg1 = BackgroundTasks()
        result1 = await start_scan(scan_id, body, bg1, store, cache, provider)
        assert result1 == {"status": "running"}
        assert scan_id in _scans_in_flight

        bg2 = BackgroundTasks()
        with pytest.raises(HTTPException) as exc_info:
            await start_scan(scan_id, body, bg2, store, cache, provider)
        assert exc_info.value.status_code == 409

        # Now actually run the (only) dispatched background task.
        await bg1()
        assert scan_id not in _scans_in_flight

    asyncio.run(scenario())

    final = store.get_scan(scan_id)
    assert final.status.value == "done"
    assert provider.call_count == 1  # one product, one call -- not doubled


# --- Important 2 (final whole-branch review): reject bad scan input -------


def test_post_scans_rejects_zero_max_concurrency(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "full", "max_concurrency": "0"},
    )

    assert response.status_code == 400


def test_post_scans_rejects_negative_max_concurrency(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "full", "max_concurrency": "-1"},
    )

    assert response.status_code == 400


def test_post_scans_rejects_zero_max_delivery_days(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "full", "max_delivery_days": "0"},
    )

    assert response.status_code == 400


def test_post_scans_rejects_negative_staleness_threshold_days(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "full", "staleness_threshold_days": "-1"},
    )

    assert response.status_code == 400


def test_post_scans_rejects_sample_scope_without_sample_per_category(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "sample"},
    )

    assert response.status_code == 400


def test_post_scans_rejects_sample_scope_with_zero_sample_per_category(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "sample", "sample_per_category": "0"},
    )

    assert response.status_code == 400


def test_post_scans_rejects_empty_csv_file(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(b""), "text/csv")},
        data={"scope_type": "full"},
    )

    assert response.status_code == 400


def test_post_scans_rejects_csv_with_unrecognizable_header(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)
    bad_csv = "foo;bar;baz;qux\nx;y;z;w\n".encode("utf-8")

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(bad_csv), "text/csv")},
        data={"scope_type": "full"},
    )

    assert response.status_code == 400


# --- Important 3 (final whole-branch review): CSV parse warnings surface --


def test_post_scans_response_includes_csv_parse_warnings(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)
    csv_bytes = (
        "nazwa;cena;ean;kategoria\n"
        "Produkt A;10,00;5901234123457;Elektronika\n"
        "Produkt B;abc;5900000000107;Dom\n"  # invalid price -> dropped, warned
    ).encode("utf-8")

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(csv_bytes), "text/csv")},
        data={"scope_type": "full"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_products"] == 1
    assert len(body["warnings"]) == 1
    assert "invalid price" in body["warnings"][0]


# --- Minor fix (final whole-branch review): bound the SSE stream for a ----
# --- scan that's never started ---------------------------------------------


def test_events_stream_stops_after_bounded_estimated_ticks(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "SSE_MAX_ESTIMATED_TICKS", 2)
    monkeypatch.setattr(api_module, "SSE_POLL_INTERVAL_SECONDS", 0.01)
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)
    scan_id = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "full"},
    ).json()["scan_id"]
    # Deliberately never started -- stays "estimated" forever.

    response = client.get(f"/scans/{scan_id}/events")

    assert response.status_code == 200
    assert '"status": "timeout"' in response.text


def test_csv_preview_returns_auto_detected_mapping_and_sample_rows(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/csv/preview", files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["headers"] == ["nazwa", "cena", "ean", "kategoria"]
    assert body["mapping"] == {
        "name": "nazwa", "wholesale_price": "cena", "ean": "ean", "category": "kategoria", "sku": None,
    }
    assert body["total_rows"] == 1
    assert body["parsed_count"] == 1
    assert body["sample_rows"][0]["nazwa"] == "Produkt A"


def test_csv_preview_returns_null_for_unresolved_field_instead_of_400(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)
    csv_bytes = ("nazwa;kategoria\nProdukt A;Elektronika\n").encode("utf-8")

    response = client.post(
        "/csv/preview", files={"file": ("catalog.csv", io.BytesIO(csv_bytes), "text/csv")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mapping"]["wholesale_price"] is None
    assert body["mapping"]["ean"] is None
    assert body["parsed_count"] == 0


def test_csv_preview_honors_a_full_mapping_override(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)
    # A header where the auto-detector would pick "cena" for price; override to point
    # wholesale_price at the ean column instead, to prove the override actually changes parsing.
    csv_bytes = (
        "nazwa;cena;ean;kategoria\n"
        "Produkt A;10,00;5901234123457;Elektronika\n"
    ).encode("utf-8")

    response = client.post(
        "/csv/preview",
        files={"file": ("catalog.csv", io.BytesIO(csv_bytes), "text/csv")},
        data={
            "name_column": "nazwa", "wholesale_price_column": "ean",
            "ean_column": "cena", "category_column": "kategoria",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mapping"]["wholesale_price"] == "ean"
    assert body["mapping"]["ean"] == "cena"


# --- Fix 4 (final whole-branch review): POST /csv/preview accepts a ------
# --- partial subset of mapping fields instead of rejecting it with 400 ----


def test_csv_preview_accepts_partial_mapping_subset(tmp_path):
    # Per the fix, /csv/preview must accept a mapping with just ONE of the 4
    # required fields provided -- the single most important interaction this
    # screen exists for: filling in one field at a time and refreshing to see
    # the effect before all 4 are done. The provided field ("name_column")
    # should be echoed back verbatim; the other 3 required fields, left
    # unset, fall back to auto-detection (all 3 are auto-detectable from
    # CSV_BYTES's headers); sku, never provided or auto-detectable here,
    # stays null.
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/csv/preview",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"name_column": "nazwa"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mapping"] == {
        "name": "nazwa", "wholesale_price": "cena", "ean": "ean", "category": "kategoria", "sku": None,
    }
    assert body["parsed_count"] == 1


def test_csv_preview_rejects_empty_csv_file(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/csv/preview", files={"file": ("catalog.csv", io.BytesIO(b""), "text/csv")},
    )

    assert response.status_code == 400


def test_post_scans_honors_a_full_mapping_override(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)
    # Same trick as the /csv/preview override test: point wholesale_price at the ean
    # column to prove the override actually reaches parsing, not just validation.
    csv_bytes = (
        "nazwa;cena;ean;kategoria\n"
        "Produkt A;10,00;99,00;Elektronika\n"
    ).encode("utf-8")

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(csv_bytes), "text/csv")},
        data={
            "scope_type": "full",
            "name_column": "nazwa", "wholesale_price_column": "ean",
            "ean_column": "cena", "category_column": "kategoria",
        },
    )

    assert response.status_code == 200
    scan_id = response.json()["scan_id"]
    pending = store.list_pending(scan_id)
    assert len(pending) == 1
    # wholesale_price_column was overridden to the "ean" column (value "99,00"),
    # not the auto-detected "cena" column (value "10,00") -- proves the override won.
    assert pending[0].product.wholesale_price == Decimal("99.00")


def test_post_scans_rejects_partial_mapping_subset(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "full", "name_column": "nazwa"},
    )

    assert response.status_code == 400


# --- Fix 5 (final whole-branch review): blank-string mapping fields must --
# --- be treated as "not provided", not as a value, by the all-or-none check


def test_post_scans_with_all_blank_mapping_fields_falls_back_to_auto_detection(tmp_path):
    # Before the fix, `_column_mapping_from_form` checked `f is not None`, so
    # 4 empty strings counted as "all 4 provided" and were passed straight
    # through as ColumnMapping(name="", ...), producing 0 parsed products and
    # a "missing name, skipped" warning per row instead of either a 400 or
    # normal auto-detection. After the fix (`if f` truthy check), blank
    # strings count as "not provided" -- with all 4 blank, that's "none
    # provided", which falls through to ordinary auto-detection, succeeding
    # exactly like `test_post_scans_still_works_with_no_mapping_fields` below.
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={
            "scope_type": "full",
            "name_column": "", "wholesale_price_column": "",
            "ean_column": "", "category_column": "",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_products"] == 1
    assert body["warnings"] == []


def test_post_scans_still_works_with_no_mapping_fields(tmp_path):
    # Backward compatibility: existing callers that never supply a mapping
    # keep getting auto-detection, unchanged from before this task.
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "full"},
    )

    assert response.status_code == 200


# --- source_type: wiring a real source (Shopify/WooCommerce) into --------
# --- POST /scans, alongside the existing default CSV upload path ----------


class _FakeWooResponse:
    def __init__(self, payload, headers=None):
        self._payload = payload
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        pass

    def json(self):
        return self._payload


class _FakeWooClient:
    """Same fixed-sequence fake used by test_woo_source.py: one currency
    call, then one response per get() call thereafter."""

    def __init__(self, currency: str, responses: list):
        self._currency = currency
        self._responses = list(responses)
        self.requests: list[dict] = []

    def get(self, url, params=None):
        self.requests.append({"url": url, "params": params})
        if len(self.requests) == 1:
            return _FakeWooResponse({"code": self._currency})
        payload = self._responses.pop(0)
        return _FakeWooResponse(payload)


def test_post_scans_rejects_unknown_source_type(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post("/scans", data={"scope_type": "full", "source_type": "bogus"})

    assert response.status_code == 400


def test_post_scans_csv_source_type_requires_a_file(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post("/scans", data={"scope_type": "full", "source_type": "csv"})

    assert response.status_code == 400


def test_post_scans_rejects_shopify_source_type_pending_hardening(tmp_path, monkeypatch):
    # ShopifyCatalogSource's GraphQL query requests ~5,050 cost points
    # against Shopify's hard 1,000-point-per-query cap (per Shopify's own
    # published API usage limits) -- it is rejected by every real store on
    # every plan, before executing. It also has no pagination cap and no
    # response-shape error handling, unlike WooCommerceCatalogSource. Gated
    # out of this endpoint until it's hardened to the same level; credentials
    # are irrelevant, the rejection must happen regardless.
    #
    # The gate must reject BEFORE ever constructing a ShopifyCatalogSource --
    # not just happen to fail once it tries a real network call against a
    # domain that doesn't exist -- so prove that directly: constructing an
    # httpx.Client inside shopify_source.py must never be reached.
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    def _fail_if_constructed(*args, **kwargs):
        raise AssertionError(
            "ShopifyCatalogSource must not be constructed while shopify is gated"
        )

    monkeypatch.setattr("app.sources.shopify_source.httpx.Client", _fail_if_constructed)

    response = client.post(
        "/scans",
        data={
            "scope_type": "full", "source_type": "shopify",
            "shop_domain": "shop.myshopify.com", "access_token": "tok",
        },
    )

    assert response.status_code == 400
    assert "shopify" in response.json()["detail"].lower()


def test_post_scans_woocommerce_source_type_requires_store_credentials(tmp_path):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/scans",
        data={
            "scope_type": "full", "source_type": "woocommerce",
            "store_url": "https://example-shop.pl", "consumer_key": "ck_test",
        },
    )

    assert response.status_code == 400


def test_post_scans_woocommerce_source_type_builds_scan_from_woocommerce_api(tmp_path, monkeypatch):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)
    fake_client = _FakeWooClient(
        currency="PLN",
        responses=[
            [
                {
                    "id": 1,
                    "type": "simple",
                    "name": "Kubek termiczny",
                    "price": "49.99",
                    "global_unique_id": "5901234123457",
                    "categories": [{"id": 9, "name": "Kuchnia", "slug": "kuchnia"}],
                }
            ],
            [],
        ],
    )
    monkeypatch.setattr(
        "app.sources.woo_source.httpx.Client", lambda *a, **kw: fake_client
    )

    response = client.post(
        "/scans",
        data={
            "scope_type": "full", "source_type": "woocommerce",
            "store_url": "https://example-shop.pl", "consumer_key": "ck_test",
            "consumer_secret": "cs_test",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_products"] == 1


# --- Code review follow-up: a Shopify/WooCommerce API failure must not ----
# --- surface as an opaque, unhandled 500 -----------------------------------


class _RaisingWooClient:
    """Simulates a non-2xx WooCommerce response: get() itself raises, same
    as `WooCommerceCatalogSource._request`'s `except httpx.HTTPError`
    path."""

    def get(self, url, params=None):
        request = httpx.Request("GET", url)
        response = httpx.Response(status_code=401, request=request)
        raise httpx.HTTPStatusError("unauthorized", request=request, response=response)


def test_post_scans_woocommerce_api_error_returns_a_client_error_not_500(tmp_path, monkeypatch):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)
    monkeypatch.setattr(
        "app.sources.woo_source.httpx.Client", lambda *a, **kw: _RaisingWooClient()
    )

    response = client.post(
        "/scans",
        data={
            "scope_type": "full", "source_type": "woocommerce",
            "store_url": "https://example-shop.pl", "consumer_key": "ck_test",
            "consumer_secret": "cs_test",
        },
    )

    assert response.status_code < 500
    assert response.status_code >= 400


# --- Code review follow-up: create_scan (which now does blocking network --
# --- I/O for Shopify/WooCommerce) must not run directly on the event loop -


def test_post_scans_offloads_create_scan_via_asyncio_to_thread(tmp_path, monkeypatch):
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)
    calls = []
    real_to_thread = asyncio.to_thread

    async def spy_to_thread(func, *args, **kwargs):
        calls.append(func)
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(api_module.asyncio, "to_thread", spy_to_thread)

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={"scope_type": "full"},
    )

    assert response.status_code == 200
    assert api_module.create_scan in calls


# --- Code review follow-up: column-mapping validation is a CSV-only -------
# --- concern and must not reject a non-CSV source_type over it ------------


def test_post_scans_woocommerce_source_type_ignores_a_stray_partial_mapping_field(
    tmp_path, monkeypatch
):
    # A partial column-mapping subset (just "name_column" here) is a 400 for
    # source_type="csv" (see test_post_scans_rejects_partial_mapping_subset),
    # but column mapping is a CSV-only concern -- for any other source_type
    # it must be ignored entirely, not misreported as a mapping error.
    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)
    fake_client = _FakeWooClient(currency="PLN", responses=[[]])
    monkeypatch.setattr(
        "app.sources.woo_source.httpx.Client", lambda *a, **kw: fake_client
    )

    response = client.post(
        "/scans",
        data={
            "scope_type": "full", "source_type": "woocommerce", "name_column": "nazwa",
            "store_url": "https://example-shop.pl", "consumer_key": "ck_test",
            "consumer_secret": "cs_test",
        },
    )

    assert response.status_code == 200


# --- Code review follow-up (minor): the WooCommerce sample_seed must not --
# --- differ just because the store_url had a trailing slash ---------------


def test_build_source_woocommerce_sample_seed_ignores_trailing_slash():
    _, seed_with_slash = _build_source(
        "woocommerce", "t1", None, None, None, None,
        "https://example-shop.pl/", "ck", "cs",
    )
    _, seed_without_slash = _build_source(
        "woocommerce", "t1", None, None, None, None,
        "https://example-shop.pl", "ck", "cs",
    )

    assert seed_with_slash == seed_without_slash


# --- Code review follow-up: a leftover uploaded file must not be read into -
# --- memory when source_type isn't "csv" -----------------------------------


def test_post_scans_woocommerce_source_type_does_not_read_a_stray_uploaded_file(
    tmp_path, monkeypatch
):
    # The type FastAPI actually constructs for an `UploadFile` parameter at
    # runtime is starlette's own UploadFile, not fastapi's subclass of it
    # (confirmed: `type(file)` inside a handler is
    # `starlette.datastructures.UploadFile`) -- patch the class whose
    # `.read` is actually invoked.
    from starlette.datastructures import UploadFile

    app, store, cache = _make_app(tmp_path)
    client = TestClient(app)
    fake_client = _FakeWooClient(currency="PLN", responses=[[]])
    monkeypatch.setattr("app.sources.woo_source.httpx.Client", lambda *a, **kw: fake_client)

    async def _fail_if_read(self, *args, **kwargs):
        raise AssertionError("file.read() must not be called for a non-csv source_type")

    monkeypatch.setattr(UploadFile, "read", _fail_if_read)

    response = client.post(
        "/scans",
        files={"file": ("catalog.csv", io.BytesIO(CSV_BYTES), "text/csv")},
        data={
            "scope_type": "full", "source_type": "woocommerce",
            "store_url": "https://example-shop.pl", "consumer_key": "ck_test",
            "consumer_secret": "cs_test",
        },
    )

    assert response.status_code == 200
