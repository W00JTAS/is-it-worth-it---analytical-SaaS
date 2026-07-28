from __future__ import annotations

import csv
import io

from app.models.product import Product
from app.normalize.ean import is_valid_ean
from app.normalize.money import InvalidPriceError, parse_price
from app.sources.column_mapping import ColumnMapping, detect_column_mapping
from app.sources.csv_detect import detect_dialect, detect_encoding


class EmptyCsvError(Exception):
    pass


class CsvCatalogSource:
    SOURCE_NAME = "csv"

    def __init__(
        self,
        file_bytes: bytes,
        tenant_id: str,
        column_mapping: ColumnMapping | None = None,
        default_currency: str = "PLN",
    ) -> None:
        self.file_bytes = file_bytes
        self.tenant_id = tenant_id
        self.column_mapping = column_mapping
        self.default_currency = default_currency
        self.warnings: list[str] = []

    def fetch_products(self) -> list[Product]:
        encoding = detect_encoding(self.file_bytes)
        text = self.file_bytes.decode(encoding)
        dialect = detect_dialect(text[:2048])
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)

        if reader.fieldnames is None:
            raise EmptyCsvError("CSV file has no header row")

        mapping = self.column_mapping or detect_column_mapping(list(reader.fieldnames))

        seen_eans: set[str] = set()
        products: list[Product] = []

        for row_index, row in enumerate(reader, start=2):
            name = (row.get(mapping.name) or "").strip()
            if not name:
                self.warnings.append(f"Row {row_index}: missing name, skipped")
                continue

            raw_price = row.get(mapping.wholesale_price) or ""
            try:
                wholesale_price = parse_price(raw_price)
            except InvalidPriceError:
                self.warnings.append(f"Row {row_index}: invalid price '{raw_price}', skipped")
                continue

            category = (row.get(mapping.category) or "").strip() or "Bez kategorii"

            raw_ean = (row.get(mapping.ean) or "").strip()
            ean: str | None = None
            if raw_ean:
                if is_valid_ean(raw_ean):
                    ean = raw_ean
                else:
                    self.warnings.append(
                        f"Row {row_index}: invalid EAN checksum '{raw_ean}', ean cleared"
                    )

            if ean is not None:
                if ean in seen_eans:
                    self.warnings.append(f"Row {row_index}: duplicate EAN '{ean}', skipped")
                    continue
                seen_eans.add(ean)

            products.append(
                Product(
                    tenant_id=self.tenant_id,
                    source=self.SOURCE_NAME,
                    external_id=str(row_index),
                    variant_id=None,
                    name=name,
                    ean=ean,
                    wholesale_price=wholesale_price,
                    currency=self.default_currency,
                    category=category,
                )
            )

        return products
