import os
from pathlib import Path

import pytest

from app.sources.csv_source import CsvCatalogSource

REAL_CATALOG_PATH = Path(
    os.environ.get("IS_IT_WORTH_IT_SAMPLE_CSV", "tests/fixtures/real_catalog.csv")
)


@pytest.mark.skipif(
    not REAL_CATALOG_PATH.exists(),
    reason=(
        f"Real catalog fixture not found at {REAL_CATALOG_PATH}; "
        "set IS_IT_WORTH_IT_SAMPLE_CSV or place the file there to run this test"
    ),
)
def test_parses_real_catalog_without_crashing():
    file_bytes = REAL_CATALOG_PATH.read_bytes()
    source = CsvCatalogSource(file_bytes=file_bytes, tenant_id="test-tenant")

    products = source.fetch_products()

    assert len(products) > 0
    assert all(p.wholesale_price >= 0 for p in products)
    print(f"Parsed {len(products)} products, {len(source.warnings)} warnings")
