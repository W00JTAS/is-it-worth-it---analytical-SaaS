from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from app.models.product import Product


def group_by_category(products: Iterable[Product]) -> dict[str, list[Product]]:
    groups: dict[str, list[Product]] = defaultdict(list)
    for product in products:
        groups[product.category].append(product)
    return dict(groups)
