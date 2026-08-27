from __future__ import annotations

import json
from typing import Any, Iterable

import httpx

from app.sources.base import BaseCatalogSource, RawItem

DEFAULT_PER_PAGE = 100


class WooCommerceApiError(Exception):
    pass


class WooCommerceCatalogSource(BaseCatalogSource):
    SOURCE_NAME = "woocommerce"

    def __init__(
        self,
        store_url: str,
        consumer_key: str,
        consumer_secret: str,
        tenant_id: str,
        client: httpx.Client | None = None,
        per_page: int = DEFAULT_PER_PAGE,
    ) -> None:
        super().__init__(tenant_id)
        self.store_url = store_url.rstrip("/")
        self.per_page = per_page
        self._client = client or httpx.Client(
            timeout=30.0, auth=(consumer_key, consumer_secret)
        )

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            response = self._client.get(f"{self.store_url}{path}", params=params or {})
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise WooCommerceApiError(f"WooCommerce request failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise WooCommerceApiError(f"WooCommerce response was not valid JSON: {exc}") from exc

    def _paginate(self, path: str) -> Iterable[dict[str, Any]]:
        page = 1
        while True:
            items = self._get(path, {"page": page, "per_page": self.per_page})
            if not isinstance(items, list):
                raise WooCommerceApiError(
                    f"WooCommerce response from {path} had an unexpected shape: "
                    f"expected a list, got {type(items).__name__}"
                )
            if not items:
                break
            yield from items
            page += 1

    def _iter_raw_items(self) -> Iterable[RawItem]:
        currency_data = self._get("/wp-json/wc/v3/data/currencies/current")
        try:
            currency = currency_data["code"]
        except (KeyError, TypeError) as exc:
            raise WooCommerceApiError(
                f"WooCommerce currency response had an unexpected shape: {exc}"
            ) from exc

        for product in self._paginate("/wp-json/wc/v3/products"):
            yield from self._map_product(product, currency)

    def _map_product(self, product: dict[str, Any], currency: str) -> Iterable[RawItem]:
        product_id = product["id"]
        product_type = product.get("type")
        name = product.get("name") or ""
        categories = product.get("categories") or []
        category = categories[0] if categories else ""

        if product_type == "simple":
            yield RawItem(
                label=f"Product {product_id}",
                external_id=str(product_id),
                variant_id=None,
                name=name,
                raw_price=product.get("price") or "",
                raw_ean=product.get("global_unique_id") or "",
                raw_category=category,
                currency=currency,
            )
        elif product_type == "variable":
            for variation in self._paginate(f"/wp-json/wc/v3/products/{product_id}/variations"):
                yield self._map_variation(product_id, name, variation, category, currency)
        else:
            self.warnings.append(
                f"Product {product_id}: unsupported type '{product_type}', skipped"
            )

    def _map_variation(
        self,
        product_id: Any,
        product_name: str,
        variation: dict[str, Any],
        category: str,
        currency: str,
    ) -> RawItem:
        variation_id = variation["id"]

        # A blank product name composed with a non-blank attribute suffix
        # would still look non-blank (e.g. "- Rozmiar: S"), silently
        # defeating BaseCatalogSource's missing-name check. Force it blank
        # so every variation of a blank-named product is skipped.
        if not product_name.strip():
            name = ""
        else:
            attributes = variation.get("attributes") or []
            suffix = ", ".join(
                f"{attr.get('name', '')}: {attr.get('option', '')}" for attr in attributes
            )
            name = f"{product_name} - {suffix}" if suffix else product_name

        return RawItem(
            label=f"Product {product_id}, variation {variation_id}",
            external_id=str(product_id),
            variant_id=str(variation_id),
            name=name,
            raw_price=variation.get("price") or "",
            raw_ean=variation.get("global_unique_id") or "",
            raw_category=category,
            currency=currency,
        )
