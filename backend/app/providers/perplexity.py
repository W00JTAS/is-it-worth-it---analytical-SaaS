from __future__ import annotations

import json
import logging
import math
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.models.product import Product
from app.providers.base import OfferResult, ProviderUnavailable

API_URL = "https://api.perplexity.ai/chat/completions"
MODEL = "sonar"

logger = logging.getLogger(__name__)

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "price": {"type": "number"},
        "currency": {"type": "string"},
        "seller": {"type": "string"},
        "source_url": {"type": "string"},
        "delivery_days": {"type": "integer"},
        "confidence": {"type": "number"},
    },
    "required": [
        "found", "price", "currency", "seller",
        "source_url", "delivery_days", "confidence",
    ],
}


class PerplexityProvider:
    name = "perplexity"

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ):
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=timeout)

    def find_cheapest(
        self, product: Product, market: str, max_delivery_days: int
    ) -> OfferResult | None:
        try:
            response = self._client.post(
                API_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": MODEL,
                    "messages": [
                        {"role": "user", "content": self._build_prompt(product, market, max_delivery_days)}
                    ],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {"name": "cheapest_offer", "schema": RESPONSE_SCHEMA},
                    },
                },
            )
            response.raise_for_status()
            response_json = response.json()
        except httpx.HTTPError as exc:
            # Transport errors (ConnectError, ReadTimeout, PoolTimeout, ...) and
            # non-2xx statuses (HTTPStatusError) are transient failures — the
            # provider was never actually consulted, so this must not be cached
            # as a genuine "no offer found" result. See ProviderUnavailable.
            logger.warning(
                "Perplexity provider request failed transiently for product %r: %s",
                product.name, exc,
            )
            raise ProviderUnavailable(str(exc)) from exc
        except json.JSONDecodeError:
            return None
        return self._parse_response(response_json, max_delivery_days)

    def _build_prompt(self, product: Product, market: str, max_delivery_days: int) -> str:
        ean_part = f" (EAN: {product.ean})" if product.ean else ""
        return (
            f'Find the cheapest real, currently-buyable offer for the product '
            f'"{product.name}"{ean_part} in the {market} market. '
            f"Only consider sellers that can deliver within {max_delivery_days} days — "
            f'if no such offer exists, set "found" to false rather than guessing. '
            f"Respond using the exact JSON schema requested, with the real source URL "
            f"you found the offer at."
        )

    def _parse_response(
        self, response_json: dict[str, Any], max_delivery_days: int
    ) -> OfferResult | None:
        raw_response = json.dumps(response_json)
        try:
            content = response_json["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            return None

        if not isinstance(parsed, dict) or not parsed.get("found"):
            return None

        source_url = parsed.get("source_url")
        if not source_url:
            return None

        currency = parsed.get("currency", "PLN")
        if not isinstance(currency, str) or not currency:
            return None

        delivery_days = parsed.get("delivery_days")
        if (
            not isinstance(delivery_days, int)
            or isinstance(delivery_days, bool)
            or delivery_days < 0
            or delivery_days > max_delivery_days
        ):
            return None

        try:
            price = Decimal(str(parsed["price"]))
        except (InvalidOperation, KeyError, TypeError):
            return None
        if not price.is_finite() or price <= 0:
            return None

        try:
            confidence = float(parsed.get("confidence", 0.0))
        except (ValueError, TypeError):
            return None
        if not math.isfinite(confidence) or not (0.0 <= confidence <= 1.0):
            return None

        raw_citations = response_json.get("citations") or []
        if isinstance(raw_citations, list):
            citations = tuple(c for c in raw_citations if isinstance(c, str))
        else:
            citations = ()

        return OfferResult(
            price=price,
            currency=currency,
            seller=parsed.get("seller", "unknown"),
            source_url=source_url,
            delivery_days=delivery_days,
            confidence=confidence,
            citations=citations,
            raw_response=raw_response,
        )
