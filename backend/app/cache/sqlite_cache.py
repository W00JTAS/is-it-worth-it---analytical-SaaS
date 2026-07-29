from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from app.providers.base import OfferResult

DEFAULT_TTL_SECONDS = 30 * 24 * 3600


@dataclass(frozen=True)
class CacheEntry:
    found: bool
    offer: OfferResult | None
    cached_at: float


class PriceCache:
    def __init__(self, db_path: str | Path, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        # check_same_thread=False: Phase 4's async/concurrent job engine will call
        # get()/set() from multiple threads/tasks sharing one PriceCache instance.
        # The lock below still serializes access from the Python side.
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._create_schema()

    def _create_schema(self) -> None:
        # WAL reduces writer/reader contention now that the SSE endpoint polls
        # the store directly on the event loop while run_scan's background
        # task reads/writes the cache concurrently.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS price_cache (
                ean TEXT NOT NULL,
                market TEXT NOT NULL,
                provider TEXT NOT NULL,
                max_delivery_days INTEGER NOT NULL,
                found INTEGER NOT NULL,
                price TEXT,
                currency TEXT,
                seller TEXT,
                source_url TEXT,
                delivery_days INTEGER,
                confidence REAL,
                citations TEXT,
                raw_response TEXT,
                cached_at REAL NOT NULL,
                PRIMARY KEY (ean, market, provider, max_delivery_days)
            )
            """
        )
        self._conn.commit()

    def get(
        self, ean: str, market: str, provider: str, max_delivery_days: int
    ) -> CacheEntry | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT found, price, currency, seller, source_url, delivery_days,
                       confidence, citations, raw_response, cached_at
                FROM price_cache
                WHERE ean = ? AND market = ? AND provider = ? AND max_delivery_days = ?
                """,
                (ean, market, provider, max_delivery_days),
            ).fetchone()
            if row is None:
                return None

            (
                found, price, currency, seller, source_url, delivery_days,
                confidence, citations, raw_response, cached_at,
            ) = row

            if time.time() - cached_at > self._ttl_seconds:
                return None

            if not found:
                return CacheEntry(found=False, offer=None, cached_at=cached_at)

            offer = OfferResult(
                price=Decimal(price),
                currency=currency,
                seller=seller,
                source_url=source_url,
                delivery_days=delivery_days,
                confidence=confidence,
                citations=tuple(json.loads(citations)),
                raw_response=raw_response,
            )
            return CacheEntry(found=True, offer=offer, cached_at=cached_at)

    def set(
        self,
        ean: str,
        market: str,
        provider: str,
        max_delivery_days: int,
        offer: OfferResult | None,
    ) -> None:
        cached_at = time.time()
        with self._lock:
            if offer is None:
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO price_cache
                        (ean, market, provider, max_delivery_days, found, cached_at)
                    VALUES (?, ?, ?, ?, 0, ?)
                    """,
                    (ean, market, provider, max_delivery_days, cached_at),
                )
            else:
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO price_cache
                        (ean, market, provider, max_delivery_days, found, price, currency,
                         seller, source_url, delivery_days, confidence, citations,
                         raw_response, cached_at)
                    VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ean, market, provider, max_delivery_days,
                        str(offer.price), offer.currency, offer.seller, offer.source_url,
                        offer.delivery_days, offer.confidence,
                        json.dumps(list(offer.citations)), offer.raw_response, cached_at,
                    ),
                )
            self._conn.commit()

    def invalidate(
        self, ean: str, market: str, provider: str, max_delivery_days: int
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                DELETE FROM price_cache
                WHERE ean = ? AND market = ? AND provider = ? AND max_delivery_days = ?
                """,
                (ean, market, provider, max_delivery_days),
            )
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()
