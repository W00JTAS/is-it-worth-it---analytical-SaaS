from __future__ import annotations

import json
import logging
from decimal import Decimal

import httpx

from app.models.product import Product
from app.providers.base import OfferResult, ProviderProfile, ProviderUnavailable
from app.providers.groq import API_URL as GROQ_API_URL
from app.providers.groq import EXTRACT_MODEL as GROQ_EXTRACT_MODEL
from app.providers.parsing import RESPONSE_SCHEMA, validate_offer_fields
from app.providers.retry import call_with_retry

SEARCH_API_URL = "https://api.firecrawl.dev/v2/search"

# Firecrawl's own docs example shows 10; matches this project's own
# investigation (task brief) which found a handful of results is usually
# enough for the extraction step to locate a genuine offer.
SEARCH_RESULT_LIMIT = 10

# ISO market code -> Firecrawl's expected `location` value: a readable place
# name (docs.firecrawl.dev/api-reference/endpoint/search, verified live
# 2026-09-01), NOT an ISO code — same idea as groq.py's MARKET_COUNTRY_NAMES
# but an independent mapping: different vendor, different casing convention
# (Firecrawl's own docs example uses "Poland", capitalized). Only the market
# this project actually uses today — see groq.py's identical reasoning. Add
# an entry here only once a second market shows up in real usage.
MARKET_LOCATION_NAMES = {
    "PL": "Poland",
}

# Conservative fallback for delivery_days when a search snippet doesn't state
# one explicitly (see _build_extract_prompt) — a common domestic-shipping
# estimate. validate_offer_fields still rejects it if it exceeds the
# caller's max_delivery_days, so this can never smuggle in a late offer.
DEFAULT_DELIVERY_DAYS = 3

logger = logging.getLogger(__name__)


class FirecrawlProvider:
    """BYOK provider backed by Firecrawl's Search API for grounding — a
    separate free-tier budget (1000 credits/month, no card) that sits
    entirely outside Groq's daily token-budget wall documented in
    .claude/rules/groq-compound-free-tier-reliability.md. Firecrawl's
    Search API returns only title/description/url snippets, not structured
    JSON, so a second, separate call to Groq's cheap gpt-oss-20b extraction
    model (same model/response_format GroqProvider._extract uses) turns
    those snippets into a validated offer. Two real HTTP calls per lookup,
    against two different services with two different API keys.
    """

    name = "firecrawl"
    # Free tier: no card required, no listed dollar price (confirmed live
    # 2026-09-01 against firecrawl.dev/pricing). A search call costs ~2
    # credits per the docs. ProviderProfile has no "N credits" field, so this
    # expresses a nominal marginal cost using the lowest published paid-tier
    # rate (~$83 / 100,000 credits => 2 credits ~= $0.0017) purely as an
    # order-of-magnitude pre-scan estimate, not a billing guarantee — see
    # ProviderProfile's own docstring caveat. seconds_per_query mirrors
    # GroqProvider's 4.0 (one search call + one extraction call) with a
    # small margin for Firecrawl's own search latency.
    profile = ProviderProfile(cost_per_query_usd=Decimal("0.0017"), seconds_per_query=5.0)

    def __init__(
        self,
        api_key: str,
        groq_api_key: str,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
        extract_model: str = GROQ_EXTRACT_MODEL,
    ):
        self._api_key = api_key
        self._groq_api_key = groq_api_key
        self._client = client or httpx.Client(timeout=timeout)
        self._extract_model = extract_model

    def find_cheapest(
        self, product: Product, market: str, max_delivery_days: int
    ) -> OfferResult | None:
        results = self._search(product, market)
        if not results:
            return None
        return self._extract(results, max_delivery_days)

    def _search(self, product: Product, market: str) -> list[dict]:
        # EAN-first: live testing during this project's investigation found
        # EAN-first queries land directly on marketplace/shop listing pages,
        # while name-only queries for less distinctive products returned
        # noisier results (see task brief).
        query = f"{product.ean} {product.name}" if product.ean else product.name
        request_body: dict = {"query": query, "limit": SEARCH_RESULT_LIMIT}
        location = MARKET_LOCATION_NAMES.get(market)
        if location is not None:
            # Omitted entirely for an unmapped market rather than sending a
            # guessed value — same reasoning as groq.py's search_settings.
            request_body["location"] = location
        try:
            response = call_with_retry(lambda: self._client.post(
                SEARCH_API_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            ))
            response_json = response.json()
        except httpx.HTTPError as exc:
            logger.warning(
                "Firecrawl search call failed transiently for product %r: %s", product.name, exc,
            )
            raise ProviderUnavailable(str(exc)) from exc
        except json.JSONDecodeError:
            return []

        try:
            web_results = response_json["data"]["web"]
        except (KeyError, TypeError):
            return []
        if not isinstance(web_results, list):
            return []
        return web_results

    def _extract(self, results: list[dict], max_delivery_days: int) -> OfferResult | None:
        # Order-preserving de-duplication, same intent as GroqProvider's
        # citation handling.
        citations = tuple(dict.fromkeys(
            r["url"] for r in results if isinstance(r, dict) and isinstance(r.get("url"), str)
        ))

        try:
            response = call_with_retry(lambda: self._client.post(
                GROQ_API_URL,
                headers={
                    "Authorization": f"Bearer {self._groq_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._extract_model,
                    "messages": [
                        {"role": "user", "content": self._build_extract_prompt(results, max_delivery_days)}
                    ],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {"name": "cheapest_offer", "schema": RESPONSE_SCHEMA},
                    },
                },
            ))
            response_json = response.json()
        except httpx.HTTPError as exc:
            logger.warning("Groq extract call failed transiently: %s", exc)
            raise ProviderUnavailable(str(exc)) from exc
        except json.JSONDecodeError:
            return None

        raw_response = json.dumps(response_json)
        try:
            content = response_json["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            return None

        return validate_offer_fields(
            parsed, raw_response=raw_response, citations=citations,
            max_delivery_days=max_delivery_days,
        )

    def _build_extract_prompt(self, results: list[dict], max_delivery_days: int) -> str:
        lines = []
        for index, result in enumerate(results, start=1):
            if not isinstance(result, dict):
                continue
            title = result.get("title", "")
            description = result.get("description", "")
            url = result.get("url", "")
            lines.append(f"{index}. {title}\n   {description}\n   {url}")
        snippets = "\n".join(lines)
        return (
            "Below is a numbered list of web search results (title / description / url) for a "
            "product. Extract the cheapest genuine, currently-buyable offer described into the "
            "requested JSON schema. Prices and sellers are often stated directly in the "
            'description text. Set "found" to false if none of the results describes a genuine '
            "current offer, or if the only offer described has delivery_days greater than "
            f"{max_delivery_days}. Only set delivery_days to a specific value when the "
            f"description text actually supports it; otherwise use {DEFAULT_DELIVERY_DAYS} as a "
            "conservative default rather than guessing.\n\n"
            f"Search results:\n{snippets}"
        )
