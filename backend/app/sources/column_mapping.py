from __future__ import annotations

from dataclasses import dataclass

NAME_ALIASES = {"nazwa", "name", "produkt", "nazwa produktu", "product name", "product"}
PRICE_ALIASES = {"cena", "cena hurtowa", "price", "wholesale price", "cena netto", "cena zakupu"}
EAN_ALIASES = {"ean", "kod ean", "barcode", "kod kreskowy", "gtin"}
CATEGORY_ALIASES = {"kategoria", "category", "grupa", "grupa produktowa"}


class ColumnMappingError(Exception):
    pass


@dataclass(frozen=True)
class ColumnMapping:
    name: str
    wholesale_price: str
    ean: str
    category: str


def detect_column_mapping(header: list[str]) -> ColumnMapping:
    normalized = {h.strip().lower(): h for h in header}

    def find(aliases: set[str], field_label: str) -> str:
        for alias in aliases:
            if alias in normalized:
                return normalized[alias]
        raise ColumnMappingError(f"Could not detect column for '{field_label}' in header {header}")

    return ColumnMapping(
        name=find(NAME_ALIASES, "name"),
        wholesale_price=find(PRICE_ALIASES, "wholesale_price"),
        ean=find(EAN_ALIASES, "ean"),
        category=find(CATEGORY_ALIASES, "category"),
    )
