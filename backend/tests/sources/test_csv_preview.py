import pytest

from app.sources.column_mapping import ColumnMapping
from app.sources.csv_preview import build_csv_preview
from app.sources.csv_source import EmptyCsvError

CSV_BYTES = (
    "nazwa;cena;ean;kategoria\n"
    "Produkt A;10,00;5901234123457;Elektronika\n"
    "Produkt B;abc;;Dom\n"
).encode("utf-8")


def test_build_preview_with_full_auto_detection():
    preview = build_csv_preview(CSV_BYTES, tenant_id="t1", mapping_override=None)

    assert preview.headers == ["nazwa", "cena", "ean", "kategoria"]
    assert preview.mapping == ColumnMapping(
        name="nazwa", wholesale_price="cena", ean="ean", category="kategoria"
    )
    assert preview.total_rows == 2
    assert preview.parsed_count == 1
    assert len(preview.warnings) == 1
    assert preview.warning_count == 1
    assert preview.sample_rows[0]["nazwa"] == "Produkt A"


def test_build_preview_with_partial_override():
    # ean is explicitly given (even though it would auto-detect the same way here);
    # the rest are left None and fall back to auto-detection.
    override = ColumnMapping(name=None, wholesale_price=None, ean="ean", category=None)

    preview = build_csv_preview(CSV_BYTES, tenant_id="t1", mapping_override=override)

    assert preview.mapping == ColumnMapping(
        name="nazwa", wholesale_price="cena", ean="ean", category="kategoria"
    )


def test_build_preview_when_required_field_cannot_be_resolved():
    csv_bytes = ("nazwa;kategoria\nProdukt A;Elektronika\n").encode("utf-8")

    preview = build_csv_preview(csv_bytes, tenant_id="t1", mapping_override=None)

    assert preview.mapping == ColumnMapping(
        name="nazwa", wholesale_price=None, ean=None, category="kategoria"
    )
    assert preview.parsed_count == 0
    assert preview.warnings == []
    assert preview.warning_count == 0
    assert preview.headers == ["nazwa", "kategoria"]
    assert preview.sample_rows[0]["nazwa"] == "Produkt A"


def test_build_preview_raises_empty_csv_error_for_missing_header():
    with pytest.raises(EmptyCsvError):
        build_csv_preview(b"", tenant_id="t1", mapping_override=None)


def test_build_preview_caps_sample_rows_and_warnings():
    header = "nazwa;cena;ean;kategoria\n"
    rows = "".join(f"Produkt {i};abc;;Dom\n" for i in range(30))
    csv_bytes = (header + rows).encode("utf-8")

    preview = build_csv_preview(csv_bytes, tenant_id="t1", mapping_override=None)

    assert preview.total_rows == 30
    assert len(preview.sample_rows) == 10
    assert len(preview.warnings) == 20
    assert preview.warning_count == 30
