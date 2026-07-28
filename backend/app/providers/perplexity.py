from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.models.product import Product
from app.providers.base import OfferResult

API_URL = "https://api.perplexity.ai/chat/completions"
MODEL = "sonar"

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
        return self._parse_response(response.json(), max_delivery_days)

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

        delivery_days = parsed.get("delivery_days")
        if not isinstance(delivery_days, int) or delivery_days > max_delivery_days:
            return None

        try:
            price = Decimal(str(parsed["price"]))
        except (InvalidOperation, KeyError, TypeError):
            return None

        citations = tuple(response_json.get("citations", []))

        return OfferResult(
            price=price,
            currency=parsed.get("currency", "PLN"),
            seller=parsed.get("seller", "unknown"),
            source_url=source_url,
            delivery_days=delivery_days,
            confidence=float(parsed.get("confidence", 0.0)),
            citations=citations,
            raw_response=raw_response,
        )
