from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from decimal import Decimal
from pathlib import Path

from app.models.product import Product
from app.providers.base import OfferResult
from app.scans.models import (
    CostEstimate,
    ProductStatus,
    Scan,
    ScanProductRecord,
    ScanStatus,
)


class ScanStore:
    def __init__(self, db_path: str | Path):
        # check_same_thread=False: Phase 4's async job engine (Task 8) will call
        # these methods from multiple threads/tasks sharing one ScanStore instance.
        # The lock below still serializes access from the Python side.
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.Lock()
        self._create_schema()

    def _create_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scans (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                scope_type TEXT NOT NULL,
                sample_per_category INTEGER,
                market TEXT NOT NULL,
                max_delivery_days INTEGER NOT NULL,
                max_concurrency INTEGER NOT NULL,
                staleness_threshold_days INTEGER NOT NULL,
                total_products INTEGER NOT NULL,
                queries_without_refresh INTEGER NOT NULL,
                queries_with_refresh INTEGER NOT NULL,
                cost_usd_without_refresh TEXT NOT NULL,
                cost_usd_with_refresh TEXT NOT NULL,
                seconds_without_refresh REAL NOT NULL,
                seconds_with_refresh REAL NOT NULL,
                overlapping_count INTEGER NOT NULL,
                stale_count INTEGER NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                source TEXT NOT NULL,
                external_id TEXT NOT NULL,
                variant_id TEXT,
                name TEXT NOT NULL,
                ean TEXT,
                wholesale_price TEXT NOT NULL,
                currency TEXT NOT NULL,
                category TEXT NOT NULL,
                status TEXT NOT NULL,
                was_stale INTEGER NOT NULL,
                offer_price TEXT,
                offer_currency TEXT,
                offer_seller TEXT,
                offer_source_url TEXT,
                offer_delivery_days INTEGER,
                offer_confidence REAL,
                offer_citations TEXT,
                offer_raw_response TEXT
            )
            """
        )
        self._conn.commit()

    def create_scan(
        self,
        *,
        scope_type: str,
        sample_per_category: int | None,
        market: str,
        max_delivery_days: int,
        max_concurrency: int,
        staleness_threshold_days: int,
        products: list[Product],
        stale_external_ids: tuple[str, ...],
        estimate: CostEstimate,
        overlapping_count: int,
        stale_count: int,
    ) -> str:
        scan_id = str(uuid.uuid4())
        stale_set = set(stale_external_ids)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO scans (
                    id, status, scope_type, sample_per_category, market, max_delivery_days,
                    max_concurrency, staleness_threshold_days, total_products,
                    queries_without_refresh, queries_with_refresh,
                    cost_usd_without_refresh, cost_usd_with_refresh,
                    seconds_without_refresh, seconds_with_refresh,
                    overlapping_count, stale_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scan_id, ScanStatus.ESTIMATED.value, scope_type, sample_per_category,
                    market, max_delivery_days, max_concurrency, staleness_threshold_days,
                    len(products), estimate.queries_without_refresh, estimate.queries_with_refresh,
                    str(estimate.cost_usd_without_refresh), str(estimate.cost_usd_with_refresh),
                    estimate.seconds_without_refresh, estimate.seconds_with_refresh,
                    overlapping_count, stale_count, time.time(),
                ),
            )
            for product in products:
                self._conn.execute(
                    """
                    INSERT INTO scan_products (
                        scan_id, tenant_id, source, external_id, variant_id, name, ean,
                        wholesale_price, currency, category, status, was_stale
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scan_id, product.tenant_id, product.source, product.external_id,
                        product.variant_id, product.name, product.ean,
                        str(product.wholesale_price), product.currency, product.category,
                        ProductStatus.PENDING.value,
                        1 if product.external_id in stale_set else 0,
                    ),
                )
            self._conn.commit()
        return scan_id

    def get_scan(self, scan_id: str) -> Scan | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT status, scope_type, sample_per_category, market, max_delivery_days,
                       max_concurrency, staleness_threshold_days, total_products,
                       queries_without_refresh, queries_with_refresh,
                       cost_usd_without_refresh, cost_usd_with_refresh,
                       seconds_without_refresh, seconds_with_refresh,
                       overlapping_count, stale_count, created_at
                FROM scans WHERE id = ?
                """,
                (scan_id,),
            ).fetchone()
            if row is None:
                return None
            (
                status, scope_type, sample_per_category, market, max_delivery_days,
                max_concurrency, staleness_threshold_days, total_products,
                queries_without_refresh, queries_with_refresh,
                cost_usd_without_refresh, cost_usd_with_refresh,
                seconds_without_refresh, seconds_with_refresh,
                overlapping_count, stale_count, created_at,
            ) = row

            completed_products = self._conn.execute(
                "SELECT COUNT(*) FROM scan_products WHERE scan_id = ? AND status != ?",
                (scan_id, ProductStatus.PENDING.value),
            ).fetchone()[0]

        return Scan(
            id=scan_id,
            status=ScanStatus(status),
            scope_type=scope_type,
            sample_per_category=sample_per_category,
            market=market,
            max_delivery_days=max_delivery_days,
            max_concurrency=max_concurrency,
            staleness_threshold_days=staleness_threshold_days,
            total_products=total_products,
            completed_products=completed_products,
            estimate=CostEstimate(
                queries_without_refresh=queries_without_refresh,
                queries_with_refresh=queries_with_refresh,
                cost_usd_without_refresh=Decimal(cost_usd_without_refresh),
                cost_usd_with_refresh=Decimal(cost_usd_with_refresh),
                seconds_without_refresh=seconds_without_refresh,
                seconds_with_refresh=seconds_with_refresh,
            ),
            overlapping_count=overlapping_count,
            stale_count=stale_count,
            created_at=created_at,
        )

    def start_scan(self, scan_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE scans SET status = ? WHERE id = ?",
                (ScanStatus.RUNNING.value, scan_id),
            )
            self._conn.commit()

    def finalize_scan(self, scan_id: str) -> None:
        with self._lock:
            remaining = self._conn.execute(
                "SELECT COUNT(*) FROM scan_products WHERE scan_id = ? AND status = ?",
                (scan_id, ProductStatus.PENDING.value),
            ).fetchone()[0]
            status = ScanStatus.DONE.value if remaining == 0 else ScanStatus.FAILED.value
            self._conn.execute(
                "UPDATE scans SET status = ? WHERE id = ?", (status, scan_id)
            )
            self._conn.commit()

    def list_pending(self, scan_id: str) -> list[ScanProductRecord]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, tenant_id, source, external_id, variant_id, name, ean,
                       wholesale_price, currency, category, was_stale
                FROM scan_products WHERE scan_id = ? AND status = ?
                """,
                (scan_id, ProductStatus.PENDING.value),
            ).fetchall()
        return [self._row_to_record(scan_id, row) for row in rows]

    def _row_to_record(self, scan_id: str, row: tuple) -> ScanProductRecord:
        (
            record_id, tenant_id, source, external_id, variant_id, name, ean,
            wholesale_price, currency, category, was_stale,
        ) = row
        product = Product(
            tenant_id=tenant_id, source=source, external_id=external_id,
            variant_id=variant_id, name=name, ean=ean,
            wholesale_price=Decimal(wholesale_price), currency=currency, category=category,
        )
        return ScanProductRecord(
            id=record_id, scan_id=scan_id, product=product,
            status=ProductStatus.PENDING, was_stale=bool(was_stale), offer=None,
        )

    def _mark(self, record_id: int, status: ProductStatus, offer: OfferResult | None) -> None:
        with self._lock:
            if offer is None:
                self._conn.execute(
                    "UPDATE scan_products SET status = ? WHERE id = ?",
                    (status.value, record_id),
                )
            else:
                self._conn.execute(
                    """
                    UPDATE scan_products SET
                        status = ?, offer_price = ?, offer_currency = ?, offer_seller = ?,
                        offer_source_url = ?, offer_delivery_days = ?, offer_confidence = ?,
                        offer_citations = ?, offer_raw_response = ?
                    WHERE id = ?
                    """,
                    (
                        status.value, str(offer.price), offer.currency, offer.seller,
                        offer.source_url, offer.delivery_days, offer.confidence,
                        json.dumps(list(offer.citations)), offer.raw_response, record_id,
                    ),
                )
            self._conn.commit()

    def mark_done(self, record_id: int, offer: OfferResult | None) -> None:
        self._mark(record_id, ProductStatus.DONE, offer)

    def mark_skipped(self, record_id: int, offer: OfferResult | None) -> None:
        self._mark(record_id, ProductStatus.SKIPPED, offer)

    def close(self) -> None:
        self._conn.close()
