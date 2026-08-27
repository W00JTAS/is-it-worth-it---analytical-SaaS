from __future__ import annotations

import csv
import io
from typing import Iterable

from app.sources.base import BaseCatalogSource, RawItem
from app.sources.column_mapping import ColumnMapping, detect_column_mapping
from app.sources.csv_detect import detect_dialect, detect_encoding


class EmptyCsvError(Exception):
    pass


class CsvCatalogSource(BaseCatalogSource):
    SOURCE_NAME = "csv"

    def __init__(
        self,
        file_bytes: bytes,
        tenant_id: str,
        column_mapping: ColumnMapping | None = None,
        default_currency: str = "PLN",
    ) -> None:
        super().__init__(tenant_id)
        self.file_bytes = file_bytes
        self.column_mapping = column_mapping
        self.default_currency = default_currency

    def _iter_raw_items(self) -> Iterable[RawItem]:
        encoding = detect_encoding(self.file_bytes)
        text = self.file_bytes.decode(encoding)
        dialect = detect_dialect(text[:2048])
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)

        if reader.fieldnames is None:
            raise EmptyCsvError("CSV file has no header row")

        mapping = self.column_mapping or detect_column_mapping(list(reader.fieldnames))

        for row_index, row in enumerate(reader, start=2):
            raw_sku = (row.get(mapping.sku) or "").strip() if mapping.sku else ""
            external_id = raw_sku or str(row_index)

            yield RawItem(
                label=f"Row {row_index}",
                external_id=external_id,
                variant_id=None,
                name=row.get(mapping.name) or "",
                raw_price=row.get(mapping.wholesale_price) or "",
                raw_ean=row.get(mapping.ean) or "",
                raw_category=row.get(mapping.category) or "",
                currency=self.default_currency,
            )
