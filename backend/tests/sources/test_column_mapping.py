import pytest

from app.sources.column_mapping import ColumnMapping, ColumnMappingError, detect_column_mapping


def test_detects_polish_headers():
    mapping = detect_column_mapping(["Nazwa", "Cena hurtowa", "EAN", "Kategoria"])
    assert mapping == ColumnMapping(
        name="Nazwa", wholesale_price="Cena hurtowa", ean="EAN", category="Kategoria"
    )


def test_detects_english_headers_case_insensitively():
    mapping = detect_column_mapping(["name", "price", "ean", "category"])
    assert mapping == ColumnMapping(name="name", wholesale_price="price", ean="ean", category="category")


def test_raises_when_a_column_cannot_be_mapped():
    with pytest.raises(ColumnMappingError):
        detect_column_mapping(["Foo", "Bar"])


def test_detects_sku_column_matching_real_supplier_header():
    mapping = detect_column_mapping(["SKU", "ean", "nazwa", "kategoria", "cena"])
    assert mapping.sku == "SKU"


def test_sku_is_none_when_no_sku_like_column_present():
    mapping = detect_column_mapping(["Nazwa", "Cena hurtowa", "EAN", "Kategoria"])
    assert mapping.sku is None


def test_prefers_more_specific_alias_when_multiple_columns_match():
    # Real Polish supplier exports commonly carry both a generic "Cena" and a
    # more specific "Cena hurtowa" column side by side. Detection must
    # deterministically prefer the more specific alias regardless of
    # PYTHONHASHSEED (this used to be a `set`, which made iteration order --
    # and therefore which column won -- nondeterministic across process runs;
    # run this test under e.g. PYTHONHASHSEED=0 and PYTHONHASHSEED=42 to
    # confirm it's seed-independent).
    mapping = detect_column_mapping(["Nazwa", "Cena", "Cena hurtowa", "EAN", "Kategoria"])
    assert mapping.wholesale_price == "Cena hurtowa"
