from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Product:
    tenant_id: str
    source: str
    external_id: str
    variant_id: str | None
    name: str
    ean: str | None
    wholesale_price: Decimal
    currency: str
    category: str
