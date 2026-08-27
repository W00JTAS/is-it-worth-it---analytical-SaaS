from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, Protocol, runtime_checkable

from app.models.product import Product
from app.normalize.ean import normalize_ean
from app.normalize.money import InvalidPriceError, parse_price


@runtime_checkable
class CatalogSource(Protocol):
    def fetch_products(self) -> Iterable[Product]:
        ...


_STRING_FIELDS = (
    "label",
    "external_id",
    "name",
    "raw_price",
    "raw_ean",
    "raw_category",
    "currency",
)


@dataclass
class RawItem:
    label: str
    external_id: str
    variant_id: str | None
    name: str
    raw_price: str
    raw_ean: str
    raw_category: str
    currency: str

    def __post_init__(self) -> None:
        # A source mapping a vendor's raw JSON must pass every field through
        # as a string -- BaseCatalogSource owns all parsing/validation. A
        # vendor field whose real shape is an object (e.g. WooCommerce's
        # `categories: [{"id": 9, "name": "..."}]`) silently produces a dict
        # here otherwise, surfacing later as an opaque AttributeError deep
        # inside `_normalize`'s `.strip()` call instead of at the source.
        for field_name in _STRING_FIELDS:
            value = getattr(self, field_name)
            if not isinstance(value, str):
                raise TypeError(f"RawItem.{field_name} must be str, got {type(value).__name__}")
        if self.variant_id is not None and not isinstance(self.variant_id, str):
            raise TypeError(
                f"RawItem.variant_id must be str or None, got {type(self.variant_id).__name__}"
            )


class BaseCatalogSource(ABC):
    SOURCE_NAME: str

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        # Fail at class-definition time, not when `_normalize` first reaches
        # for `self.SOURCE_NAME` deep inside a fetch (potentially after a
        # paid external API round-trip). `"SOURCE_NAME" in cls.__dict__`
        # rather than `hasattr(cls, "SOURCE_NAME")`: the latter would also be
        # satisfied by a value inherited from a parent class, which is not
        # what "this subclass forgot to set it" means.
        if "SOURCE_NAME" not in cls.__dict__:
            raise TypeError(f"{cls.__name__} must set SOURCE_NAME")

    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        self.warnings: list[str] = []

    @abstractmethod
    def _iter_raw_items(self) -> Iterable[RawItem]:
        ...

    def fetch_products(self) -> list[Product]:
        seen_eans: dict[str, int] = {}
        products: list[Product] = []
        for item in self._iter_raw_items():
            product = self._normalize(item)
            if product is not None:
                self._append_with_dedup(products, seen_eans, item.label, product)
        return products

    def _normalize(self, item: RawItem) -> Product | None:
        name = item.name.strip()
        if not name:
            self.warnings.append(f"{item.label}: missing name, skipped")
            return None

        try:
            wholesale_price = parse_price(item.raw_price)
        except InvalidPriceError:
            self.warnings.append(f"{item.label}: invalid price '{item.raw_price}', skipped")
            return None

        if wholesale_price == 0:
            self.warnings.append(f"{item.label}: zero price, skipped")
            return None

        category = item.raw_category.strip() or "Bez kategorii"

        ean, ean_warning = normalize_ean(item.raw_ean)
        if ean_warning is not None:
            self.warnings.append(f"{item.label}: {ean_warning}")

        return Product(
            tenant_id=self.tenant_id,
            source=self.SOURCE_NAME,
            external_id=item.external_id,
            variant_id=item.variant_id,
            name=name,
            ean=ean,
            wholesale_price=wholesale_price,
            currency=item.currency,
            category=category,
        )

    def _append_with_dedup(
        self,
        products: list[Product],
        seen_eans: dict[str, int],
        label: str,
        product: Product,
    ) -> None:
        # Maps a seen EAN to its product's index in `products`, so a later
        # duplicate that turns out to be cheaper can update the kept
        # product in place (preserving first-occurrence ordering) rather than
        # being appended as a second entry.
        if product.ean is not None and product.ean in seen_eans:
            existing_index = seen_eans[product.ean]
            existing = products[existing_index]
            if product.wholesale_price < existing.wholesale_price:
                self.warnings.append(
                    f"{label}: duplicate EAN '{product.ean}', replaced previously kept "
                    f"item (price {existing.wholesale_price}) with this cheaper item "
                    f"(price {product.wholesale_price})"
                )
                # A later cheaper duplicate overwrites the kept product in
                # place, preserving first-occurrence *ordering* (it stays at
                # `existing_index`) -- not identity: the whole record becomes
                # the new, cheaper one.
                products[existing_index] = product
            else:
                self.warnings.append(
                    f"{label}: duplicate EAN '{product.ean}', dropped (price "
                    f"{product.wholesale_price} not cheaper than kept price "
                    f"{existing.wholesale_price})"
                )
            return

        products.append(product)
        if product.ean is not None:
            seen_eans[product.ean] = len(products) - 1
