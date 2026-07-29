from __future__ import annotations

import random

from app.models.product import Product


def resolve_sample_scope(
    products_by_category: dict[str, list[Product]],
    target_per_category: int,
    seed: int,
) -> list[Product]:
    category_names = sorted(products_by_category.keys())
    sizes = {name: len(products_by_category[name]) for name in category_names}

    allocation: dict[str, int] = {}
    over_target: list[str] = []
    pool = 0

    for name in category_names:
        size = sizes[name]
        if size <= target_per_category:
            allocation[name] = size
            pool += target_per_category - size
        else:
            allocation[name] = target_per_category
            over_target.append(name)

    while pool > 0 and over_target:
        share, remainder = divmod(pool, len(over_target))

        if share == 0:
            for name in over_target[:remainder]:
                allocation[name] += 1
            break

        pool = remainder
        still_over_target: list[str] = []
        for name in over_target:
            size = sizes[name]
            candidate_allocation = allocation[name] + share
            if candidate_allocation >= size:
                pool += candidate_allocation - size
                allocation[name] = size
            else:
                allocation[name] = candidate_allocation
                still_over_target.append(name)
        over_target = still_over_target

    rng = random.Random(seed)
    selected: list[Product] = []
    for name in category_names:
        candidates = products_by_category[name]
        count = allocation[name]
        if count >= len(candidates):
            selected.extend(candidates)
        else:
            selected.extend(rng.sample(candidates, count))
    return selected
