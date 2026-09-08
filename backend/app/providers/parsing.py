from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

from app.providers.base import OfferResult

# Price-comparison / deal-aggregator sites confirmed live (2026-09-08 eval
# run) to slip past the extraction prompt's explicit "prefer the seller's
# own page" instruction — in 3/23 found offers, despite it. One of the three (a
# skapiec.pl comparison page) carried a price that matched nothing on the
# actual cited page, i.e. likely fabricated on top of the wrong provenance.
# A prose instruction is not reliable enough on its own; a hostname check is
# deterministic and can't be talked out of its answer. Only domains actually
# observed live go here — see MARKET_LOCATION_NAMES in firecrawl.py for the
# same "don't pre-populate speculative entries" reasoning.
AGGREGATOR_DOMAINS: frozenset[str] = frozenset({"ceneo.pl", "skapiec.pl"})


def _is_aggregator_url(url: str) -> bool:
    hostname = (urlparse(url).hostname or "").lower()
    return hostname in AGGREGATOR_DOMAINS or any(
        hostname.endswith(f".{domain}") for domain in AGGREGATOR_DOMAINS
    )

# A grounded search occasionally has the model write a currency symbol
# instead of an ISO 4217 code (e.g. "zł" for PLN) — observed in the same
# eval run, where it caused real offers to be wrongly excluded downstream
# by evaluate.py's strict
# `currency != product.currency` comparison. Normalize before that
# comparison ever sees the value.
CURRENCY_SYMBOL_ALIASES: dict[str, str] = {
    "zł": "PLN",
    "zl": "PLN",
    "€": "EUR",
    "$": "USD",
    "£": "GBP",
}


def normalize_currency(raw: str) -> str:
    stripped = raw.strip()
    if len(stripped) == 3 and stripped.isalpha():
        return stripped.upper()
    return CURRENCY_SYMBOL_ALIASES.get(stripped, stripped)


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


def validate_offer_fields(
    parsed: object,
    *,
    raw_response: str,
    citations: tuple[str, ...],
    max_delivery_days: int,
) -> OfferResult | None:
    """Validates a provider's already-extracted offer JSON against the shared
    contract. Provider-agnostic: PerplexityProvider and GroqProvider both
    parse their own response envelope down to this dict shape first, then
    call this — so the two providers' offers can never diverge on what
    counts as a valid one, even though they write into the same price_cache.
    """
    if not isinstance(parsed, dict) or not parsed.get("found"):
        return None

    source_url = parsed.get("source_url")
    if not source_url:
        return None
    if _is_aggregator_url(source_url):
        return None

    currency = parsed.get("currency", "PLN")
    if not isinstance(currency, str) or not currency:
        return None
    currency = normalize_currency(currency)

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
