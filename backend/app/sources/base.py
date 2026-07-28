from __future__ import annotations

from typing import Iterable, Protocol, runtime_checkable

from app.models.product import Product


@runtime_checkable
class CatalogSource(Protocol):
    def fetch_products(self) -> Iterable[Product]:
        ...
