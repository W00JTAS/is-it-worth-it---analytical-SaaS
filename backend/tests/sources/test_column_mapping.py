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
