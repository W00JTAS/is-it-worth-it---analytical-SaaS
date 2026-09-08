from decimal import Decimal

from app.sources.csv_source import CsvCatalogSource

VALID_EAN = "5901234123457"

HEADER = "Nazwa;Cena hurtowa;EAN;Kategoria\n"


def _csv(rows: str) -> bytes:
    return (HEADER + rows).encode("utf-8")


def test_parses_valid_row():
    source = CsvCatalogSource(_csv(f"Łóżko;100,00;{VALID_EAN};Meble\n"), tenant_id="t1")
    products = source.fetch_products()
    assert len(products) == 1
    product = products[0]
    assert product.name == "Łóżko"
    assert product.wholesale_price == Decimal("100.00")
    assert product.ean == VALID_EAN
    assert product.category == "Meble"
    assert product.tenant_id == "t1"
    assert product.source == "csv"
    assert product.currency == "PLN"


def test_parses_cp1250_encoded_file():
    raw = (HEADER + f"Łóżko;100,00;{VALID_EAN};Meble\n").encode("cp1250")
    source = CsvCatalogSource(raw, tenant_id="t1")
    products = source.fetch_products()
    assert products[0].name == "Łóżko"


def test_parses_comma_delimited_file():
    raw = f"Nazwa,Cena hurtowa,EAN,Kategoria\nŁóżko,100.00,{VALID_EAN},Meble\n".encode("utf-8")
    source = CsvCatalogSource(raw, tenant_id="t1")
    products = source.fetch_products()
    assert products[0].wholesale_price == Decimal("100.00")


def test_external_id_falls_back_to_row_index_without_sku_column():
    source = CsvCatalogSource(_csv(f"Łóżko;100,00;{VALID_EAN};Meble\n"), tenant_id="t1")
    products = source.fetch_products()
    assert len(products) == 1
    assert products[0].external_id == "2"


def test_external_id_uses_sku_column_when_present():
    header = "SKU;Nazwa;Cena hurtowa;EAN;Kategoria\n"
    row = f"ABC-123;Łóżko;100,00;{VALID_EAN};Meble\n"
    source = CsvCatalogSource((header + row).encode("utf-8"), tenant_id="t1")
    products = source.fetch_products()
    assert len(products) == 1
    assert products[0].external_id == "ABC-123"


def test_skips_row_with_comma_decimal_zero_price():
    # Regression for a real 115k-row supplier file
    # where ~37k rows carried a "0,00" zero-price marker in Polish
    # comma-decimal form. This is CSV-format-specific: it proves the CSV row
    # (semicolon-delimited, comma-decimal) actually reaches the base's
    # zero-price check as "0" and gets skipped, not just that the generic
    # parser rejects "0.00" in isolation.
    source = CsvCatalogSource(_csv(f"Łóżko;0,00;{VALID_EAN};Meble\n"), tenant_id="t1")
    products = source.fetch_products()
    assert products == []
    assert any("zero price" in w for w in source.warnings)


def test_parses_bom_prefixed_csv_end_to_end():
    # b"\xef\xbb\xbf" is the UTF-8 BOM Excel-on-Windows prepends when exporting
    # CSV. Previously this raised ColumnMappingError because the BOM ended up
    # glued to the first header cell ("﻿Nazwa" matched no alias).
    raw = b"\xef\xbb\xbf" + _csv(f"Łóżko;100,00;{VALID_EAN};Meble\n")
    source = CsvCatalogSource(raw, tenant_id="t1")
    products = source.fetch_products()
    assert len(products) == 1
    assert products[0].name == "Łóżko"
