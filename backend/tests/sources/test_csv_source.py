from decimal import Decimal

from app.sources.csv_source import CsvCatalogSource

VALID_EAN = "5901234123457"
INVALID_EAN = "5901234123458"
# UPC-A (12-digit) barcode that checksum-validates as EAN-13 once zero-padded
# (verified: is_valid_ean("0" + UPC_A) is True).
UPC_A = "698813001132"
PADDED_UPC_A = "0" + UPC_A

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


def test_skips_row_with_missing_name():
    source = CsvCatalogSource(_csv(f";100,00;{VALID_EAN};Meble\n"), tenant_id="t1")
    products = source.fetch_products()
    assert len(products) == 0
    assert any("missing name" in w for w in source.warnings)


def test_skips_row_with_invalid_price():
    source = CsvCatalogSource(_csv(f"Łóżko;not-a-price;{VALID_EAN};Meble\n"), tenant_id="t1")
    products = source.fetch_products()
    assert len(products) == 0
    assert any("invalid price" in w for w in source.warnings)


def test_clears_ean_with_bad_checksum_but_keeps_row():
    source = CsvCatalogSource(_csv(f"Łóżko;100,00;{INVALID_EAN};Meble\n"), tenant_id="t1")
    products = source.fetch_products()
    assert len(products) == 1
    assert products[0].ean is None
    assert any("invalid EAN checksum" in w for w in source.warnings)


def test_duplicate_ean_keeps_first_when_first_is_cheaper():
    rows = f"Łóżko;100,00;{VALID_EAN};Meble\nStół;200,00;{VALID_EAN};Meble\n"
    source = CsvCatalogSource(_csv(rows), tenant_id="t1")
    products = source.fetch_products()
    assert len(products) == 1
    assert products[0].name == "Łóżko"
    assert products[0].wholesale_price == Decimal("100.00")
    assert any("duplicate EAN" in w for w in source.warnings)


def test_duplicate_ean_replaces_with_cheaper_later_row():
    rows = f"Łóżko;200,00;{VALID_EAN};Meble\nStół;100,00;{VALID_EAN};Meble\n"
    source = CsvCatalogSource(_csv(rows), tenant_id="t1")
    products = source.fetch_products()
    assert len(products) == 1
    assert products[0].name == "Stół"
    assert products[0].wholesale_price == Decimal("100.00")
    assert any("duplicate EAN" in w for w in source.warnings)


def test_duplicate_ean_three_rows_keeps_cheapest_at_first_position():
    rows = (
        f"Łóżko;200,00;{VALID_EAN};Meble\n"
        f"Stół;300,00;{VALID_EAN};Meble\n"
        f"Krzesło;100,00;{VALID_EAN};Meble\n"
    )
    source = CsvCatalogSource(_csv(rows), tenant_id="t1")
    products = source.fetch_products()
    assert len(products) == 1
    assert products[0].name == "Krzesło"
    assert products[0].wholesale_price == Decimal("100.00")
    assert sum("duplicate EAN" in w for w in source.warnings) == 2


def test_missing_category_defaults_to_uncategorized():
    source = CsvCatalogSource(_csv(f"Łóżko;100,00;{VALID_EAN};\n"), tenant_id="t1")
    products = source.fetch_products()
    assert products[0].category == "Bez kategorii"


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


def test_skips_row_with_zero_price():
    source = CsvCatalogSource(_csv(f"Łóżko;0,00;{VALID_EAN};Meble\n"), tenant_id="t1")
    products = source.fetch_products()
    assert len(products) == 0
    assert any("zero price" in w for w in source.warnings)


def test_skips_row_with_zero_price_no_decimals():
    source = CsvCatalogSource(_csv(f"Łóżko;0;{VALID_EAN};Meble\n"), tenant_id="t1")
    products = source.fetch_products()
    assert len(products) == 0
    assert any("zero price" in w for w in source.warnings)


def test_zero_pads_valid_upc_a_barcode_to_ean13():
    source = CsvCatalogSource(_csv(f"Łóżko;100,00;{UPC_A};Meble\n"), tenant_id="t1")
    products = source.fetch_products()
    assert len(products) == 1
    assert products[0].ean == PADDED_UPC_A
    assert len(products[0].ean) == 13


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


def test_parses_bom_prefixed_csv_end_to_end():
    # b"\xef\xbb\xbf" is the UTF-8 BOM Excel-on-Windows prepends when exporting
    # CSV. Previously this raised ColumnMappingError because the BOM ended up
    # glued to the first header cell ("﻿Nazwa" matched no alias).
    raw = b"\xef\xbb\xbf" + _csv(f"Łóżko;100,00;{VALID_EAN};Meble\n")
    source = CsvCatalogSource(raw, tenant_id="t1")
    products = source.fetch_products()
    assert len(products) == 1
    assert products[0].name == "Łóżko"
