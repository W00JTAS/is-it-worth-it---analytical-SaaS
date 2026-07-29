from decimal import Decimal

from app.models.product import Product
from app.scans.sampling import resolve_sample_scope


def _make_products(category: str, count: int, start: int = 0) -> list[Product]:
    return [
        Product(
            tenant_id="t1", source="csv", external_id=f"{category}-{i}", variant_id=None,
            name=f"{category} product {i}", ean=None,
            wholesale_price=Decimal("10.00"), currency="PLN", category=category,
        )
        for i in range(start, start + count)
    ]


def test_exact_fit_takes_target_from_each_category():
    products_by_category = {
        "A": _make_products("A", 50),
        "B": _make_products("B", 50),
    }

    result = resolve_sample_scope(products_by_category, target_per_category=50, seed=1)

    assert len(result) == 100


def test_short_category_donates_shortfall_to_pool_evenly():
    # A has only 20 (target 50) -> shortfall of 30 goes into the pool, split evenly
    # between B and C (both comfortably over target), 15 each.
    products_by_category = {
        "A": _make_products("A", 20),
        "B": _make_products("B", 200),
        "C": _make_products("C", 200),
    }

    result = resolve_sample_scope(products_by_category, target_per_category=50, seed=1)

    by_category: dict[str, int] = {}
    for p in result:
        by_category[p.category] = by_category.get(p.category, 0) + 1

    assert by_category["A"] == 20  # took everything, couldn't hit target
    assert by_category["B"] == 65  # 50 + 15 from the pool
    assert by_category["C"] == 65  # 50 + 15 from the pool
    assert len(result) == 150


def test_uneven_pool_remainder_is_dropped_deterministically():
    # A has 0 (shortfall = target, e.g. 10) -> pool = 10, split between 3
    # over-target categories (B, C, D): 10 // 3 = 3 each, remainder 1 goes to
    # the alphabetically-first category with room (B), C and D get nothing extra.
    products_by_category = {
        "A": [],
        "B": _make_products("B", 100),
        "C": _make_products("C", 100),
        "D": _make_products("D", 100),
    }

    result = resolve_sample_scope(products_by_category, target_per_category=10, seed=1)

    by_category: dict[str, int] = {}
    for p in result:
        by_category[p.category] = by_category.get(p.category, 0) + 1

    assert "A" not in by_category  # took everything (zero), nothing to include
    assert by_category["B"] == 14  # 10 + 3 (share) + 1 (remainder, first alphabetically)
    assert by_category["C"] == 13  # 10 + 3 (share)
    assert by_category["D"] == 13  # 10 + 3 (share)
    assert len(result) == 40


def test_multi_round_redistribution_when_a_category_overflows_its_own_size():
    # A: 0 (shortfall 10). B: 12 (just over target of 10, only 2 spare capacity).
    # C: 100 (plenty of room).
    # Pool = 10, split evenly between B and C (5 each) in round 1: B would need
    # 10+5=15 but only has 12 -> caps at 12 (donates 3 back to the pool), C
    # takes 10+5=15. Pool after round 1 = 3, only C has room left -> C takes all 3.
    # Final: A=0, B=12, C=18.
    products_by_category = {
        "A": [],
        "B": _make_products("B", 12),
        "C": _make_products("C", 100),
    }

    result = resolve_sample_scope(products_by_category, target_per_category=10, seed=1)

    by_category: dict[str, int] = {}
    for p in result:
        by_category[p.category] = by_category.get(p.category, 0) + 1

    assert "A" not in by_category
    assert by_category["B"] == 12
    assert by_category["C"] == 18
    assert len(result) == 30


def test_same_seed_gives_same_sample_twice():
    products_by_category = {"A": _make_products("A", 200)}

    first = resolve_sample_scope(products_by_category, target_per_category=10, seed=42)
    second = resolve_sample_scope(products_by_category, target_per_category=10, seed=42)

    assert [p.external_id for p in first] == [p.external_id for p in second]


def test_different_seed_can_give_a_different_sample():
    products_by_category = {"A": _make_products("A", 200)}

    first = resolve_sample_scope(products_by_category, target_per_category=10, seed=1)
    second = resolve_sample_scope(products_by_category, target_per_category=10, seed=2)

    # Not a hard guarantee for any possible RNG, but true for Python's Random
    # with these seeds and this sample size — a meaningful smoke check that the
    # seed actually participates in the selection.
    assert [p.external_id for p in first] != [p.external_id for p in second]
