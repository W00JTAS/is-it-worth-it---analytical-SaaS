from __future__ import annotations

from typing import Any

import httpx

from app.models.product import Product
from app.normalize.ean import is_valid_ean
from app.normalize.money import InvalidPriceError, parse_price

DEFAULT_API_VERSION = "2026-07"

CURRENCY_QUERY = "{ shop { currencyCode } }"

PRODUCTS_QUERY = """
query($cursor: String) {
  products(first: 50, after: $cursor) {
    edges {
      node {
        id
        title
        productType
        variants(first: 100) {
          edges {
            node {
              id
              title
              price
              barcode
            }
          }
        }
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""


class ShopifyCatalogSource:
    SOURCE_NAME = "shopify"

    def __init__(
        self,
        shop_domain: str,
        access_token: str,
        tenant_id: str,
        client: httpx.Client | None = None,
        api_version: str = DEFAULT_API_VERSION,
    ) -> None:
        self.shop_domain = shop_domain
        self.access_token = access_token
        self.tenant_id = tenant_id
        self.api_version = api_version
        self._client = client or httpx.Client(timeout=30.0)
        self.warnings: list[str] = []

    @property
    def _url(self) -> str:
        return f"https://{self.shop_domain}/admin/api/{self.api_version}/graphql.json"

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "X-Shopify-Access-Token": self.access_token,
            "Content-Type": "application/json",
        }

    def _post(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self._client.post(
            self._url,
            headers=self._headers,
            json={"query": query, "variables": variables or {}},
        )
        response.raise_for_status()
        body = response.json()
        return body["data"]

    def fetch_products(self) -> list[Product]:
        currency = self._post(CURRENCY_QUERY)["shop"]["currencyCode"]

        products: list[Product] = []
        cursor: str | None = None
        while True:
            data = self._post(PRODUCTS_QUERY, {"cursor": cursor})["products"]
            for edge in data["edges"]:
                products.extend(self._map_product(edge["node"], currency))

            page_info = data["pageInfo"]
            if not page_info["hasNextPage"]:
                break
            cursor = page_info["endCursor"]

        return products

    def _map_product(self, node: dict[str, Any], currency: str) -> list[Product]:
        product_id = node["id"]
        title = node["title"]
        category = node.get("productType") or "Bez kategorii"

        mapped: list[Product] = []
        for variant_edge in node["variants"]["edges"]:
            variant = variant_edge["node"]
            variant_id = variant["id"]

            raw_price = variant.get("price") or ""
            try:
                wholesale_price = parse_price(raw_price)
            except InvalidPriceError:
                self.warnings.append(
                    f"Product {product_id}, variant {variant_id}: invalid price "
                    f"'{raw_price}', skipped"
                )
                continue

            if wholesale_price == 0:
                self.warnings.append(
                    f"Product {product_id}, variant {variant_id}: zero price, skipped"
                )
                continue

            variant_title = variant.get("title") or "Default Title"
            name = title if variant_title == "Default Title" else f"{title} - {variant_title}"

            raw_barcode = (variant.get("barcode") or "").strip()
            ean: str | None = None
            if raw_barcode:
                if is_valid_ean(raw_barcode):
                    ean = raw_barcode
                else:
                    self.warnings.append(
                        f"Product {product_id}, variant {variant_id}: invalid EAN "
                        f"checksum '{raw_barcode}', ean cleared"
                    )

            mapped.append(
                Product(
                    tenant_id=self.tenant_id,
                    source=self.SOURCE_NAME,
                    external_id=product_id,
                    variant_id=variant_id,
                    name=name,
                    ean=ean,
                    wholesale_price=wholesale_price,
                    currency=currency,
                    category=category,
                )
            )

        return mapped
