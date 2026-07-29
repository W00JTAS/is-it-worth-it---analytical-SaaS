from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.models.product import Product
from app.providers.base import OfferResult


class ScanStatus(str, Enum):
    ESTIMATED = "estimated"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class ProductStatus(str, Enum):
    PENDING = "pending"
    DONE = "done"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class CostEstimate:
    queries_without_refresh: int
    queries_with_refresh: int
    cost_usd_without_refresh: Decimal
    cost_usd_with_refresh: Decimal
    seconds_without_refresh: float
    seconds_with_refresh: float


@dataclass(frozen=True)
class StalenessReport:
    overlapping_count: int
    stale_external_ids: tuple[str, ...]


@dataclass(frozen=True)
class Scan:
    id: str
    status: ScanStatus
    scope_type: str
    sample_per_category: int | None
    market: str
    max_delivery_days: int
    max_concurrency: int
    staleness_threshold_days: int
    total_products: int
    completed_products: int
    estimate: CostEstimate
    created_at: float


@dataclass(frozen=True)
class ScanProductRecord:
    id: int
    scan_id: str
    product: Product
    status: ProductStatus
    was_stale: bool
    offer: OfferResult | None
