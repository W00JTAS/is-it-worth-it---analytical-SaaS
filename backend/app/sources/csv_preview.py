from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from app.sources.column_mapping import ColumnMapping, detect_column_mapping_partial
from app.sources.csv_detect import detect_dialect, detect_encoding
from app.sources.csv_source import CsvCatalogSource, EmptyCsvError

SAMPLE_ROW_LIMIT = 10
WARNING_LIMIT = 20


@dataclass(frozen=True)
class CsvPreview:
    headers: list[str]
    mapping: ColumnMapping
    sample_rows: list[dict[str, str]]
    total_rows: int
    parsed_count: int
    warnings: list[str]
    warning_count: int


def _merge_mapping(override: ColumnMapping | None, detected: ColumnMapping) -> ColumnMapping:
    if override is None:
        return detected
    return ColumnMapping(
        name=override.name or detected.name,
        wholesale_price=override.wholesale_price or detected.wholesale_price,
        ean=override.ean or detected.ean,
        category=override.category or detected.category,
        sku=override.sku or detected.sku,
    )


def build_csv_preview(
    csv_bytes: bytes, tenant_id: str, mapping_override: ColumnMapping | None
) -> CsvPreview:
    encoding = detect_encoding(csv_bytes)
    text = csv_bytes.decode(encoding)
    dialect = detect_dialect(text[:2048])
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)

    if reader.fieldnames is None:
        raise EmptyCsvError("CSV file has no header row")

    headers = list(reader.fieldnames)
    rows = list(reader)

    mapping = _merge_mapping(mapping_override, detect_column_mapping_partial(headers))

    sample_rows = [
        {k: (v if v is not None else "") for k, v in row.items()}
        for row in rows[:SAMPLE_ROW_LIMIT]
    ]
    total_rows = len(rows)

    parsed_count = 0
    warnings: list[str] = []
    if mapping.name and mapping.wholesale_price and mapping.ean and mapping.category:
        source = CsvCatalogSource(csv_bytes, tenant_id=tenant_id, column_mapping=mapping)
        parsed_count = len(source.fetch_products())
        warnings = source.warnings

    return CsvPreview(
        headers=headers,
        mapping=mapping,
        sample_rows=sample_rows,
        total_rows=total_rows,
        parsed_count=parsed_count,
        warnings=warnings[:WARNING_LIMIT],
        warning_count=len(warnings),
    )
