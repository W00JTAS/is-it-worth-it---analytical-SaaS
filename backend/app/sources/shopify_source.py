from __future__ import annotations

import json
from typing import Any

import httpx

from app.models.product import Product
from app.normalize.ean import is_valid_ean
from app.normalize.money import InvalidPriceError, parse_price

DEFAULT_API_VERSION = "2026-07"

CURRENCY_QUERY = "{ shop { currencyCode } }"


class ShopifyApiError(Exception):
    pass


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
        try:
            response = self._client.post(
                self._url,
                headers=self._headers,
                json={"query": query, "variables": variables or {}},
            )
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError as exc:
            raise ShopifyApiError(f"Shopify request failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ShopifyApiError(f"Shopify response was not valid JSON: {exc}") from exc

        try:
            if "errors" in body:
                messages = "; ".join(e.get("message", str(e)) for e in body["errors"])
                raise ShopifyApiError(f"Shopify GraphQL error: {messages}")

            return body["data"]
        except (KeyError, AttributeError, TypeError) as exc:
            raise ShopifyApiError(f"Shopify response had an unexpected shape: {exc}") from exc

    def fetch_products(self) -> list[Product]:
        currency = self._post(CURRENCY_QUERY)["shop"]["currencyCode"]

        # Maps a seen EAN to its product's index in `products`, so a later
        # duplicate that turns out to be cheaper can overwrite the kept
        # product in place (preserving first-occurrence ordering) rather than
        # being appended as a second entry. Mirrors CsvCatalogSource's dedup.
        seen_eans: dict[str, int] = {}
        products: list[Product] = []
        cursor: str | None = None
        while True:
            data = self._post(PRODUCTS_QUERY, {"cursor": cursor})["products"]
            for edge in data["edges"]:
                for product in self._map_product(edge["node"], currency):
                    self._append_with_dedup(products, seen_eans, product)

            page_info = data["pageInfo"]
            if not page_info["hasNextPage"]:
                break

            next_cursor = page_info["endCursor"]
            if next_cursor == cursor:
                raise ShopifyApiError(
                    "Shopify pagination did not advance — endCursor did not change "
                    "across pages"
                )
            cursor = next_cursor

        return products

    def _append_with_dedup(
        self,
        products: list[Product],
        seen_eans: dict[str, int],
        product: Product,
    ) -> None:
        if product.ean is not None and product.ean in seen_eans:
            existing_index = seen_eans[product.ean]
            existing = products[existing_index]
            if product.wholesale_price < existing.wholesale_price:
                self.warnings.append(
                    f"Product {product.external_id}, variant {product.variant_id}: "
                    f"duplicate EAN '{product.ean}', replaced previously kept product "
                    f"(price {existing.wholesale_price}) with this cheaper variant "
                    f"(price {product.wholesale_price})"
                )
                products[existing_index] = product
            else:
                self.warnings.append(
                    f"Product {product.external_id}, variant {product.variant_id}: "
                    f"duplicate EAN '{product.ean}', dropped (price "
                    f"{product.wholesale_price} not cheaper than kept price "
                    f"{existing.wholesale_price})"
                )
            return

        products.append(product)
        if product.ean is not None:
            seen_eans[product.ean] = len(products) - 1

    def _map_product(self, node: dict[str, Any], currency: str) -> list[Product]:
        product_id = node["id"]
        title = (node.get("title") or "").strip()
        if not title:
            self.warnings.append(f"Product {product_id}: missing title, skipped")
            return []
        category = (node.get("productType") or "").strip() or "Bez kategorii"

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
            if len(raw_barcode) == 12 and raw_barcode.isdigit():
                # UPC-A is numerically identical to EAN-13 with a leading zero.
                raw_barcode = "0" + raw_barcode
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
