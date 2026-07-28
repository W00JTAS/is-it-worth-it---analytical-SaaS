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

        # Maps a seen EAN to its product's index in `products`, so a later
        # duplicate that turns out to be cheaper can overwrite the kept
        # product in place (preserving first-occurrence ordering) rather than
        # being appended as a second entry.
        seen_eans: dict[str, int] = {}
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

            if wholesale_price == 0:
                self.warnings.append(f"Row {row_index}: zero price, skipped")
                continue

            category = (row.get(mapping.category) or "").strip() or "Bez kategorii"

            raw_ean = (row.get(mapping.ean) or "").strip()
            if len(raw_ean) == 12 and raw_ean.isdigit():
                # UPC-A is numerically identical to EAN-13 with a leading zero.
                raw_ean = "0" + raw_ean
            ean: str | None = None
            if raw_ean:
                if is_valid_ean(raw_ean):
                    ean = raw_ean
                else:
                    self.warnings.append(
                        f"Row {row_index}: invalid EAN checksum '{raw_ean}', ean cleared"
                    )

            raw_sku = (row.get(mapping.sku) or "").strip() if mapping.sku else ""
            external_id = raw_sku or str(row_index)

            product = Product(
                tenant_id=self.tenant_id,
                source=self.SOURCE_NAME,
                external_id=external_id,
                variant_id=None,
                name=name,
                ean=ean,
                wholesale_price=wholesale_price,
                currency=self.default_currency,
                category=category,
            )

            if ean is not None and ean in seen_eans:
                existing_index = seen_eans[ean]
                existing_price = products[existing_index].wholesale_price
                if wholesale_price < existing_price:
                    self.warnings.append(
                        f"Row {row_index}: duplicate EAN '{ean}', replaced previously kept "
                        f"product (price {existing_price}) with this cheaper row (price {wholesale_price})"
                    )
                    products[existing_index] = product
                else:
                    self.warnings.append(
                        f"Row {row_index}: duplicate EAN '{ean}', dropped (price {wholesale_price} "
                        f"not cheaper than kept price {existing_price})"
                    )
                continue

            products.append(product)
            if ean is not None:
                seen_eans[ean] = len(products) - 1

        return products
