from __future__ import annotations

import json
from typing import Any, Iterable

import httpx

from app.sources.base import BaseCatalogSource, RawItem

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


class ShopifyCatalogSource(BaseCatalogSource):
    SOURCE_NAME = "shopify"

    def __init__(
        self,
        shop_domain: str,
        access_token: str,
        tenant_id: str,
        client: httpx.Client | None = None,
        api_version: str = DEFAULT_API_VERSION,
    ) -> None:
        super().__init__(tenant_id)
        self.shop_domain = shop_domain
        self.access_token = access_token
        self.api_version = api_version
        self._client = client or httpx.Client(timeout=30.0)

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

    def _iter_raw_items(self) -> Iterable[RawItem]:
        currency = self._post(CURRENCY_QUERY)["shop"]["currencyCode"]

        cursor: str | None = None
        while True:
            data = self._post(PRODUCTS_QUERY, {"cursor": cursor})["products"]
            for edge in data["edges"]:
                yield from self._map_product(edge["node"], currency)

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

    def _map_product(self, node: dict[str, Any], currency: str) -> Iterable[RawItem]:
        product_id = node["id"]
        title = (node.get("title") or "").strip()
        category = node.get("productType") or ""

        for variant_edge in node["variants"]["edges"]:
            variant = variant_edge["node"]
            variant_id = variant["id"]
            variant_title = variant.get("title") or "Default Title"

            # A blank title composed with a non-default variant title would
            # still look non-blank (e.g. "- S"), silently defeating
            # BaseCatalogSource's missing-name check. Force it blank so every
            # variant of a blank-titled product is skipped, not just the
            # Default Title one.
            if not title:
                name = ""
            elif variant_title == "Default Title":
                name = title
            else:
                name = f"{title} - {variant_title}"

            yield RawItem(
                label=f"Product {product_id}, variant {variant_id}",
                external_id=product_id,
                variant_id=variant_id,
                name=name,
                raw_price=variant.get("price") or "",
                raw_ean=variant.get("barcode") or "",
                raw_category=category,
                currency=currency,
            )
