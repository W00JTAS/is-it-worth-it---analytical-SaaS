from __future__ import annotations

import json
from typing import Any, Iterable

import httpx

from app.sources.base import BaseCatalogSource, RawItem

DEFAULT_PER_PAGE = 100

# `X-WP-TotalPages` (always sent by the WordPress REST API, per its own
# docs) is the authoritative stop signal and is used when present. This cap
# is only the fallback for a store that omits it: pagination advances by
# incrementing `page`, and a page number always "advances" even if the
# server ignores it (a caching proxy or CDN serving a stale page 1
# forever) -- unlike Shopify's cursor, which can be checked for "did it
# actually move".
MAX_PAGES = 2_000


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

    def _request(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            response = self._client.get(f"{self.store_url}{path}", params=params or {})
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            raise WooCommerceApiError(f"WooCommerce request failed: {exc}") from exc

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = self._request(path, params)
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise WooCommerceApiError(f"WooCommerce response was not valid JSON: {exc}") from exc

    def _paginate(self, path: str) -> Iterable[dict[str, Any]]:
        page = 1
        total_pages: int | None = None
        while True:
            if page > MAX_PAGES:
                raise WooCommerceApiError(
                    f"WooCommerce pagination for {path} did not terminate within "
                    f"{MAX_PAGES} pages"
                )
            response = self._request(path, {"page": page, "per_page": self.per_page})

            if total_pages is None:
                header_value = response.headers.get("X-WP-TotalPages")
                if header_value is not None:
                    try:
                        total_pages = int(header_value)
                    except ValueError:
                        total_pages = None

            try:
                items = response.json()
            except json.JSONDecodeError as exc:
                raise WooCommerceApiError(
                    f"WooCommerce response was not valid JSON: {exc}"
                ) from exc
            if not isinstance(items, list):
                raise WooCommerceApiError(
                    f"WooCommerce response from {path} had an unexpected shape: "
                    f"expected a list, got {type(items).__name__}"
                )
            if not items:
                break
            yield from items

            if total_pages is not None and page >= total_pages:
                break
            page += 1

    def _iter_raw_items(self) -> Iterable[RawItem]:
        try:
            yield from self._iter_raw_items_unsafe()
        except (KeyError, AttributeError, TypeError) as exc:
            raise WooCommerceApiError(
                f"WooCommerce response had an unexpected shape: {exc}"
            ) from exc

    def _iter_raw_items_unsafe(self) -> Iterable[RawItem]:
        currency_data = self._get("/wp-json/wc/v3/data/currencies/current")
        try:
            currency = currency_data["code"]
        except (KeyError, TypeError) as exc:
            raise WooCommerceApiError(
                f"WooCommerce currency response had an unexpected shape: {exc}"
            ) from exc

        for product in self._paginate("/wp-json/wc/v3/products"):
            yield from self._map_product(product, currency)

    def _build_raw_item(self, **kwargs: Any) -> RawItem:
        # RawItem.__post_init__ (app/sources/base.py) raises a bare
        # TypeError when a field isn't the scalar it's declared as -- catch
        # it here so a vendor field with an unexpected shape (e.g. a number
        # instead of a string) surfaces as WooCommerceApiError like every
        # other shape problem in this file, not as an uncaught TypeError.
        try:
            return RawItem(**kwargs)
        except TypeError as exc:
            raise WooCommerceApiError(
                f"WooCommerce response had an unexpected field shape: {exc}"
            ) from exc

    def _map_product(self, product: dict[str, Any], currency: str) -> Iterable[RawItem]:
        try:
            product_id = product["id"]
            product_type = product.get("type")
            name = product.get("name") or ""
            categories = product.get("categories") or []
            category = (categories[0].get("name") or "") if categories else ""
        except (KeyError, AttributeError, TypeError) as exc:
            raise WooCommerceApiError(
                f"WooCommerce product response had an unexpected shape: {exc}"
            ) from exc

        if product_type == "simple":
            yield self._build_raw_item(
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
        try:
            variation_id = variation["id"]

            # A blank product name composed with a non-blank attribute
            # suffix would still look non-blank (e.g. "- Rozmiar: S"),
            # silently defeating BaseCatalogSource's missing-name check.
            # Force it blank so every variation of a blank-named product is
            # skipped.
            if not product_name.strip():
                name = ""
            else:
                attributes = variation.get("attributes") or []
                parts = []
                for attr in attributes:
                    attr_name = attr.get("name")
                    attr_option = attr.get("option")
                    if not isinstance(attr_name, (str, type(None))) or not isinstance(
                        attr_option, (str, type(None))
                    ):
                        raise TypeError(
                            f"variation attribute had a non-string name/option: {attr!r}"
                        )
                    parts.append(f"{attr_name or ''}: {attr_option or ''}")
                suffix = ", ".join(parts)
                name = f"{product_name} - {suffix}" if suffix else product_name
        except (KeyError, AttributeError, TypeError) as exc:
            raise WooCommerceApiError(
                f"WooCommerce variation response had an unexpected shape: {exc}"
            ) from exc

        return self._build_raw_item(
            label=f"Product {product_id}, variation {variation_id}",
            external_id=str(product_id),
            variant_id=str(variation_id),
            name=name,
            raw_price=variation.get("price") or "",
            raw_ean=variation.get("global_unique_id") or "",
            raw_category=category,
            currency=currency,
        )
