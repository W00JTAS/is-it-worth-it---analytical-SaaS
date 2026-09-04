from __future__ import annotations

import json
import logging
from decimal import Decimal

import httpx

from app.models.product import Product
from app.providers.base import OfferResult, ProviderProfile, ProviderUnavailable
from app.providers.groq import API_URL as GROQ_API_URL
from app.providers.groq import EXTRACT_MAX_TOKENS as GROQ_EXTRACT_MAX_TOKENS
from app.providers.groq import EXTRACT_MODEL as GROQ_EXTRACT_MODEL
from app.providers.groq import EXTRACT_REASONING_EFFORT as GROQ_EXTRACT_REASONING_EFFORT
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

# Shopping-intent keywords appended to the search query for a known market.
# Live-verified 2026-09-02: a bare product-name/EAN query is dominated by
# manufacturer spec pages whose Firecrawl snippet never states a price (JS-
# rendered price widgets aren't in the static meta description Firecrawl
# scrapes) — appending local shopping words biases results toward listing/
# price-comparison pages that DO state a price in the snippet text. Example:
# "Słuchawki TWS Edifier W200T czarne" alone returned 0/20 results with a
# visible PLN price; the same query + "cena zł" returned 6/10 with one.
# Omitted for an unmapped market, same reasoning as MARKET_LOCATION_NAMES.
MARKET_SHOPPING_TERMS = {
    "PL": "cena zł",
}

# Conservative fallback for delivery_days when a search snippet doesn't state
# one explicitly (see _build_extract_prompt) — a common domestic-shipping
# estimate. validate_offer_fields still rejects it if it exceeds the
# caller's max_delivery_days, so this can never smuggle in a late offer.
DEFAULT_DELIVERY_DAYS = 3

logger = logging.getLogger(__name__)


def _error_detail(body: dict) -> str:
    """Best-effort human-readable detail out of a Firecrawl `success: false`
    body. Deliberately defensive: the exact error field name on a failed
    v2/search response is not confirmed against a live failure (only against
    the docs' success shape), so this tries the plausible names and falls
    back to the whole body rather than raising a KeyError of its own inside
    an error path.
    """
    for key in ("error", "message", "detail", "warning"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value
        if value is not None:
            return repr(value)
    return f"no error detail in response body ({body!r})"


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
        # Same contract as GroqProvider.last_search_text: exposes the search
        # step's raw grounding material to callers that want it (e.g.
        # provider_eval.py's --keep-raw) without changing find_cheapest's
        # return type. For Firecrawl the "search text" is the rendered
        # snippet block that the extraction step actually sees. Reset at the
        # start of every call and set right after the search step, before any
        # early return, so a caller reading it after a `None` result always
        # sees THIS call's snippets rather than a previous product's.
        self.last_search_text: str | None = None

    def find_cheapest(
        self, product: Product, market: str, max_delivery_days: int
    ) -> OfferResult | None:
        self.last_search_text = None
        results = self._search(product, market)
        self.last_search_text = self._format_snippets(results)
        if not results:
            return None
        return self._extract(results, market, max_delivery_days)

    def _search(self, product: Product, market: str) -> list[dict]:
        # EAN-first: live testing during this project's investigation found
        # EAN-first queries land directly on marketplace/shop listing pages,
        # while name-only queries for less distinctive products returned
        # noisier results (see task brief).
        query = f"{product.ean} {product.name}" if product.ean else product.name
        shopping_term = MARKET_SHOPPING_TERMS.get(market)
        if shopping_term is not None:
            query = f"{query} {shopping_term}"
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
        except json.JSONDecodeError as exc:
            # An unparseable body is not "the search found nothing" — the
            # call never produced a usable answer at all. Returning [] here
            # would surface as a legitimate `None` from find_cheapest and be
            # persisted as a negative cache entry (see base.py's
            # ProviderUnavailable vs None contract).
            raise ProviderUnavailable(
                f"Firecrawl search response body was not valid JSON: {exc}"
            ) from exc

        # Firecrawl reports its own failures in-band: HTTP 200 with
        # "success": false in the body. Nothing above catches that, so
        # without this check a failed search falls through to the data.web
        # lookup, comes back empty, and is misreported as a genuine
        # "no offers exist" — cacheable negative, per base.py's contract.
        # Only an explicit False counts: a body with no "success" key at all
        # (older/other shapes) is left to the data.web lookup below.
        if isinstance(response_json, dict) and response_json.get("success") is False:
            raise ProviderUnavailable(
                f"Firecrawl search reported success=false: {_error_detail(response_json)}"
            )

        try:
            web_results = response_json["data"]["web"]
        except (KeyError, TypeError):
            return []
        if not isinstance(web_results, list):
            return []
        return web_results

    def _extract(
        self, results: list[dict], market: str, max_delivery_days: int
    ) -> OfferResult | None:
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
                        {
                            "role": "user",
                            "content": self._build_extract_prompt(results, market, max_delivery_days),
                        }
                    ],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {"name": "cheapest_offer", "schema": RESPONSE_SCHEMA},
                    },
                    "max_tokens": GROQ_EXTRACT_MAX_TOKENS,
                    "reasoning_effort": GROQ_EXTRACT_REASONING_EFFORT,
                },
            ))
            response_json = response.json()
        except httpx.HTTPError as exc:
            logger.warning("Groq extract call failed transiently: %s", exc)
            raise ProviderUnavailable(str(exc)) from exc
        except json.JSONDecodeError as exc:
            raise ProviderUnavailable(
                f"Groq extract response body was not valid JSON: {exc}"
            ) from exc

        raw_response = json.dumps(response_json)
        # An unparseable envelope/content is NOT the model saying "no offer".
        # A genuine negative is a well-formed {"found": false, ...} object,
        # which falls through to validate_offer_fields below and correctly
        # returns None (a cacheable negative). Garbage that never reached the
        # schema at all is an unavailability, per base.py's contract.
        try:
            content = response_json["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderUnavailable(
                f"Groq extract response was unparseable ({type(exc).__name__}: {exc})"
            ) from exc
        if not isinstance(parsed, dict) or "found" not in parsed:
            raise ProviderUnavailable(
                "Groq extract response did not contain the expected schema "
                f"object (no 'found' key): {parsed!r}"
            )

        return validate_offer_fields(
            parsed, raw_response=raw_response, citations=citations,
            max_delivery_days=max_delivery_days,
        )

    @staticmethod
    def _format_snippets(results: list[dict]) -> str:
        """Renders the search results as the numbered title/description/url
        block the extraction model sees. Shared with `last_search_text` so
        --keep-raw records exactly the material the extraction worked from,
        not a separate rendering that could drift from it.
        """
        lines = []
        for index, result in enumerate(results, start=1):
            if not isinstance(result, dict):
                continue
            title = result.get("title", "")
            description = result.get("description", "")
            url = result.get("url", "")
            lines.append(f"{index}. {title}\n   {description}\n   {url}")
        return "\n".join(lines)

    def _build_extract_prompt(self, results: list[dict], market: str, max_delivery_days: int) -> str:
        snippets = self._format_snippets(results)
        # min(): if max_delivery_days itself is below the generic default (1
        # or 2 days), the fallback must not exceed it either, or
        # validate_offer_fields would reject every unstated-delivery-time
        # offer outright.
        default_delivery_days = min(DEFAULT_DELIVERY_DAYS, max_delivery_days)
        return (
            "Below is a numbered list of web search results (title / description / url) for a "
            "product. Extract the cheapest genuine, currently-buyable offer described into the "
            "requested JSON schema. Prices and sellers are often stated directly in the "
            "description text.\n\n"
            "source_url must be a specific product listing page for THIS product — never a "
            "search-results page, a category/browse page, or a price-comparison hub page. If a "
            "result's description shows a price but the result itself is a category or search "
            "page (e.g. its title mentions a size/model range wider than this exact product, or "
            "the URL clearly points at a search or category path), do not use that price — it "
            "likely belongs to a different, unrelated item on that page, not this product. Only "
            "extract a price you can verify is stated specifically for this exact product on its "
            "own listing.\n\n"
            "A result can also be a price-comparison or deal-aggregator page (e.g. it lists "
            "\"now €X at [some other store]\" rather than being that store's own listing), or a "
            "page that is no longer available — a 404 / \"page not found\" result, or a page "
            "whose own content says the product wasn't found — or a listing explicitly marked "
            "out of stock, backordered, discontinued, or withdrawn from sale (e.g. \"wycofane z "
            "oferty\", \"niedostępny\", \"out of stock\"). None of these count as a genuine, "
            'currently-buyable offer — do not extract a price from one, even if a price is '
            "shown; prefer a different result that is the actual seller's own, live, in-stock "
            'listing, or set "found" to false if none of the results qualifies.\n\n'
            "A single result's description can also contain more than one price even on a "
            "genuine, correctly-matched product page — for example a much smaller price for an "
            "accessory or a 'buy this too for only X' upsell, or because the description text "
            "drifts partway through into describing a DIFFERENT product (a different model, "
            "color, capacity, or lumen/spec count) that happens to share the same page or listing "
            "block as the one you're looking for. Only use a price whose surrounding text still "
            "names or describes THIS exact product — if a price is attached to text describing a "
            "different item's name or attributes, it belongs to that different item, not this one. "
            "Before finalizing, also sanity-check the price against the range mentioned in the "
            "OTHER results below for the same product: a legitimate price is usually within the "
            "same rough order of magnitude as most other listings, even if it's the cheapest of a "
            "close cluster — but if your candidate is a small fraction of what every other listing "
            "states (not just the lowest of a similar cluster, but dramatically below all of them), "
            "that is a strong signal you picked up an accessory, upsell, or unrelated item's price "
            "— prefer a result whose price agrees with the broader range instead, or set \"found\" "
            "to false if none does.\n\n"
            f"Only count an offer as valid if it is deliverable to a buyer in {market} within "
            f"{max_delivery_days} days — the seller can be based anywhere, as long as the listing "
            f"indicates it ships to {market} in time; do not reject an offer merely for being "
            f"listed on a site not based in {market}. A listing on a marketplace or store that is "
            f"clearly domestic to {market} (a country-specific domain, or a price already stated "
            f"in {market}'s own local currency) should be treated as deliverable to {market} by "
            f"default even when the snippet text never spells out a shipping destination — do not "
            f"reject a domestic listing merely for not stating the obvious. Report the price in "
            f'the currency actually stated for that offer, not a converted or assumed one. Set '
            f'"found" to false if none '
            f"of the results describes a genuine current offer deliverable to {market} in time, or "
            f"if the only offer described has delivery_days greater than {max_delivery_days}. Only "
            "set delivery_days to a specific value when the description text actually supports it; "
            f"otherwise use {default_delivery_days} as a conservative default rather than "
            "guessing.\n\n"
            f"Search results:\n{snippets}"
        )
