from __future__ import annotations

from dataclasses import dataclass

# Ordered most-specific-first: when a header contains multiple aliases for the
# same field (e.g. both "Cena" and "Cena hurtowa"), the earlier (more specific)
# match wins. These must stay tuples, not sets -- set iteration order is
# randomized per-process (PYTHONHASHSEED), which made column detection
# nondeterministic across runs.
NAME_ALIASES = ("nazwa produktu", "product name", "nazwa", "produkt", "name", "product")
PRICE_ALIASES = ("cena hurtowa", "cena zakupu", "cena netto", "wholesale price", "cena", "price")
EAN_ALIASES = ("kod ean", "kod kreskowy", "ean", "barcode", "gtin")
CATEGORY_ALIASES = ("grupa produktowa", "kategoria", "category", "grupa")
# Supplier's stable product identifier. Optional -- unlike the four aliases
# above, a missing SKU column is not an error; callers fall back to the CSV
# row index (see CsvCatalogSource.fetch_products).
SKU_ALIASES = ("sku", "kod sku", "symbol")


class ColumnMappingError(Exception):
    pass


@dataclass(frozen=True)
class ColumnMapping:
    name: str
    wholesale_price: str
    ean: str
    category: str
    sku: str | None = None


def detect_column_mapping(header: list[str]) -> ColumnMapping:
    normalized = {h.strip().lower(): h for h in header}

    def find(aliases: tuple[str, ...], field_label: str) -> str:
        for alias in aliases:
            if alias in normalized:
                return normalized[alias]
        raise ColumnMappingError(f"Could not detect column for '{field_label}' in header {header}")

    def find_optional(aliases: tuple[str, ...]) -> str | None:
        for alias in aliases:
            if alias in normalized:
                return normalized[alias]
        return None

    return ColumnMapping(
        name=find(NAME_ALIASES, "name"),
        wholesale_price=find(PRICE_ALIASES, "wholesale_price"),
        ean=find(EAN_ALIASES, "ean"),
        category=find(CATEGORY_ALIASES, "category"),
        sku=find_optional(SKU_ALIASES),
    )
