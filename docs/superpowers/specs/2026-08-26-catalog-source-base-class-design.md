# Shared `CatalogSource` normalization layer + `add-catalog-source` skill — design

Master plan: `docs/superpowers/specs/2026-07-28-is-it-worth-it-design.md`, line 148 (the
`add-catalog-source` skill was named there as meta-layer work, deferred until a second source
existed to design it against). Surfaced as a concrete follow-up in
`docs/superpowers/specs/2026-08-26-phase-7-meta-writeup.md`, point 4, and carried forward by
`.claude/handoffs/handoff_10.md`.

## Why now

Two `CatalogSource` implementations exist (`CsvCatalogSource`, `ShopifyCatalogSource`), and a third
(WooCommerce) is planned. The repo-reviewer memory file
`.claude/agent-memory/repo-reviewer/source-protocol-invariants.md`, written during the Phase 6
Shopify sketch, found that the `CatalogSource` `Protocol` declares one method
(`fetch_products()`) but the real contract is a five-part normalization pipeline that exists only
as duplicated hand-written logic in each source file:

1. Blank/missing name → skip, with a warning.
2. Zero price → skip, with a warning.
3. Category: strip, blank → `"Bez kategorii"`.
4. EAN: 12-digit numeric → zero-pad to 13 (UPC-A/EAN-13 equivalence); then checksum-validate via
   `is_valid_ean`; invalid → clear the field with a warning, keep the row.
5. EAN dedup across the whole fetch: on a repeated EAN, keep whichever row is cheaper, with a
   warning either way.

A sixth item is duplicated but not safety-critical: `self.warnings: list[str] = []` initialization
itself.

The Shopify implementation reproduced all five by hand and got them right, but nothing in the type
system would have caught it if it hadn't — `isinstance(source, CatalogSource)` and the full test
suite (208 passed) both pass regardless of whether these invariants are honored. The memory file's
own stale-when condition names the fix: *"the normalisation moves into a shared helper or base
class every source calls, so a new source cannot omit it."* This design is that fix, done before a
third source makes the duplication a three-way maintenance burden instead of a two-way one.

## Goal

A new source can only be *wrong* about format-specific mapping (which GraphQL field is the price,
which CSV column is the EAN) — never about whether to dedup by EAN, pad a UPC-A, or skip a blank
name. Enforced by construction, not by review.

**Out of scope:** the WooCommerce source itself (this is prep work, not that phase); CSV-format
internals (`column_mapping.py`, `csv_detect.py`, `csv_preview.py`) — unrelated to the shared
invariants; the standing deferred items already tracked in `handoff_10.md` (Shopify live smoke
test, `add-price-provider` skill, Allegro, `backend/.gitignore`).

## Architecture

### `RawItem` and `BaseCatalogSource` (`app/sources/base.py`)

```python
@dataclass
class RawItem:
    label: str            # e.g. "Row 5" or "Product gid://…/1, variant gid://…/2"
    external_id: str
    variant_id: str | None
    name: str              # raw, unstripped, possibly blank
    raw_price: str
    raw_ean: str            # raw barcode/EAN string, possibly empty
    raw_category: str
    currency: str

class BaseCatalogSource(ABC):
    SOURCE_NAME: str

    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        self.warnings: list[str] = []

    @abstractmethod
    def _iter_raw_items(self) -> Iterable[RawItem]: ...

    def fetch_products(self) -> list[Product]:
        seen_eans: dict[str, int] = {}
        products: list[Product] = []
        for item in self._iter_raw_items():
            product = self._normalize(item)
            if product is not None:
                self._append_with_dedup(products, seen_eans, product)
        return products
```

`_normalize(item) -> Product | None` and `_append_with_dedup(products, seen_eans, product)` are
private methods on `BaseCatalogSource`, carrying the five invariants exactly as they behave today
(same warning wording, same skip/keep semantics), with one deliberate exception noted below. EAN
padding + checksum validation moves into a new `normalize_ean(raw: str) -> tuple[str | None, str |
None]` function in `app/normalize/ean.py` (returns the normalized EAN or `None`, and a warning
suffix or `None`), so it is unit-testable independent of any source. Category and name/price
handling stay inline in `_normalize` — each is one line, not worth their own module.

The existing `CatalogSource` `Protocol` in the same file is unchanged. `BaseCatalogSource` satisfies
it structurally (it has a `fetch_products` method), so any existing `isinstance(source,
CatalogSource)` check keeps working without modification.

### Behavior change: Shopify's missing-name warning granularity

Today, `ShopifyCatalogSource._map_product` checks the product `title` once and, if blank, skips the
*entire product* (all its variants) with **one** warning: `"Product {id}: missing title, skipped"`.

Under the shared `_normalize`, the blank-name check runs per `RawItem`, and Shopify's
`_iter_raw_items` yields one `RawItem` per *variant*. A blank title therefore produces **one
warning per variant** (`"Product {id}, variant {id}: missing name, skipped"`), not one per product.
The end result is identical (all variants of that product are dropped either way); only the warning
count and wording change — "name" replaces "title" for consistency with the `Product.name` field
used everywhere else. `test_shopify_source.py`'s existing assertion on this message text is updated
accordingly (see Testing).

### `CsvCatalogSource` (`app/sources/csv_source.py`)

Becomes `class CsvCatalogSource(BaseCatalogSource)`. Constructor and `EmptyCsvError` are unchanged.
`fetch_products` is deleted; `_iter_raw_items` keeps the encoding/dialect detection and
`csv.DictReader` loop, and yields one `RawItem` per row (`label=f"Row {row_index}"`) with raw,
unvalidated field values. No normalization logic remains in this file.

### `ShopifyCatalogSource` (`app/sources/shopify_source.py`)

Becomes `class ShopifyCatalogSource(BaseCatalogSource)`. Constructor, `_url`, `_headers`, `_post`,
and the GraphQL pagination loop are unchanged. `fetch_products`, `_append_with_dedup`, and
`_map_product`'s normalization logic are deleted; `_iter_raw_items` keeps the pagination + currency
lookup and yields one `RawItem` per variant (`label=f"Product {product_id}, variant {variant_id}"`)
with raw field values.

## Testing

New `tests/sources/test_base_source.py` tests the five invariants once, directly against
`BaseCatalogSource`, using a minimal `FakeSource(BaseCatalogSource)` whose `_iter_raw_items` returns
a canned, test-supplied list of `RawItem`s. This is where
`test_skips_row_with_missing_name`-style cases (missing name, zero price, category fallback,
UPC-A padding, invalid checksum, dedup-cheapest-wins in both orderings) live going forward.

`test_csv_source.py` keeps only CSV-format concerns that `test_base_source.py` cannot cover:
encoding/dialect detection, `EmptyCsvError`, column-mapping interaction, row-numbering in labels.
Any of its existing cases that duplicate an invariant already covered by the new base-class suite
are deleted, not kept as a redundant second copy.

`test_shopify_source.py` keeps only GraphQL concerns: pagination cursor advancing (including the
non-advancing-cursor error case), response-shape error handling, currency lookup. Its missing-title
assertion is updated to match the new per-variant/"missing name" wording described above.

No test changes are needed for `test_csv_source_integration.py` or `test_shopify_source_live.py` —
both exercise end-to-end behavior that is unaffected by where the normalization code lives.

## `add-catalog-source` skill

New `.claude/skills/add-catalog-source/SKILL.md`. Triggers when a new catalog source is being
added (e.g. "add a WooCommerce source"). Contents:

1. Create `app/sources/<name>_source.py` with `class <Name>CatalogSource(BaseCatalogSource)`,
   `SOURCE_NAME = "<name>"`.
2. Implement only `_iter_raw_items(self) -> Iterable[RawItem]`, mapping the source format's raw
   fields into `RawItem`. Explicit instruction: **do not** re-validate, strip, pad, or dedup here —
   pass raw strings through; `BaseCatalogSource` owns every normalization decision. This is the
   line the skill exists to hold: it is exactly the step where the Shopify sketch could have (and,
   per the memory file, easily could have) silently diverged.
3. Give each `RawItem` a `label` that identifies the row/item in warnings (mirror the existing
   `"Row N"` / `"Product X, variant Y"` conventions).
4. Write format-specific tests only (mirror `test_csv_source.py` / `test_shopify_source.py`'s
   post-refactor scope) — the five shared invariants are already covered by
   `test_base_source.py` and do not need re-testing per source.
5. Wire the new source into `app/scans/orchestration.py` (or wherever it needs to be reachable) if
   applicable.
6. Run the `repo-reviewer` subagent before merging, per this project's whole-branch review
   convention.

## Definition of done

- `pytest` in `backend/` green, including the new `test_base_source.py` and the trimmed
  `test_csv_source.py` / `test_shopify_source.py`.
- `CsvCatalogSource` and `ShopifyCatalogSource` contain zero normalization logic — grep confirms
  neither file matches `strip()\|is_valid_ean\|len(raw\|seen_eans\|Bez kategorii` outside of
  `_iter_raw_items` passing raw values through.
- `.claude/skills/add-catalog-source/SKILL.md` exists and is committed.
- `.claude/agent-memory/repo-reviewer/source-protocol-invariants.md`'s "Stale when" condition is
  now true; update that file to point at `BaseCatalogSource` instead of describing the gap.
