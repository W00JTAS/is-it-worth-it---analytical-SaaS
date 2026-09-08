from __future__ import annotations

import json
import logging
from decimal import Decimal

import httpx

from app.models.product import Product
from app.providers.base import OfferResult, ProviderProfile, ProviderUnavailable
from app.providers.liveness import is_confirmed_dead
from app.providers.parsing import RESPONSE_SCHEMA, validate_offer_fields
from app.providers.retry import call_with_retry

API_URL = "https://api.groq.com/openai/v1/chat/completions"
SEARCH_MODEL = "groq/compound-mini"
EXTRACT_MODEL = "openai/gpt-oss-20b"

# ISO market code -> Groq's expected search_settings.country value: a full
# country name, lowercase (console.groq.com/docs/web-search#search-settings,
# verified live 2026-09-01) — NOT an ISO code. Only markets this project
# actually uses today (grepped app/scans/, app/models/product.py: "PL" is
# the only market code that appears anywhere in the codebase, incl. the
# scans API's default). Add an entry here only once a second market shows
# up in real usage — don't pre-populate speculative ones.
MARKET_COUNTRY_NAMES = {
    "PL": "poland",
}

# Generous cap on the search call's response tokens: a genuine answer is a
# few sentences (price, currency, seller, one URL, delivery estimate) —
# comfortably under 150 tokens in observed responses — so 600 leaves ample
# headroom for a verbose multi-sentence answer while still bounding the
# worst case (a model that rambles) against the scarce daily token budget
# documented in .claude/rules/groq-compound-free-tier-reliability.md.
SEARCH_MAX_TOKENS = 600

# Token-diet caps for the EXTRACTION call (gpt-oss-20b), shared by both
# GroqProvider._extract and FirecrawlProvider._extract — the two call sites
# that hit this same model with the same fixed-instructions-plus-snippet
# prompt shape. Measured live 2026-09-03 against a real stored search
# snippet via _build_extract_prompt, three calls:
#   1. no params (today's default): 1459 reasoning_tokens, 1579
#      completion_tokens, 3759 total_tokens.
#   2. reasoning_effort="low": 125 reasoning_tokens, 198 completion_tokens,
#      2345 total_tokens — reasoning cut by ~91%.
#   3. reasoning_effort="low" + max_tokens=350: 54 reasoning_tokens, 115
#      completion_tokens, 2441 total_tokens, finish_reason="stop" — i.e. the
#      350 cap did NOT truncate a genuine successful answer.
# EXTRACT_MAX_TOKENS=500 leaves comfortable headroom over the observed
# 115-198 completion tokens while still bounding a runaway far below the
# uncapped sample's 1579. Full data at the time of measurement: see
# .superpowers/sdd/kontynuuj-wczoraj-przerwa-em-prace-dynamic-feather/
# progress.md's "Controller-run: live token measurement" section — but
# that SDD workspace is deleted once this plan finishes, so the numbers
# above are restated in full rather than only pointed to.
EXTRACT_MAX_TOKENS = 500
EXTRACT_REASONING_EFFORT = "low"

logger = logging.getLogger(__name__)


class GroqProvider:
    """Free-tier BYOK provider. Two real HTTP calls per lookup because Groq's
    compound-mini (web search) is documented as incompatible with structured
    outputs in the same request (console.groq.com/docs/structured-outputs:
    "tool use is not currently supported with Structured Outputs") — so
    grounding and JSON-schema extraction are two separate calls, the second
    on a model (gpt-oss-20b) that does support response_format=json_schema.
    """

    name = "groq"
    # Free tier: no dollar cost. seconds_per_query is a documented estimate
    # (two sequential Groq calls, plus a bounded liveness HEAD check on a
    # found offer's source_url — see app/providers/liveness.py, added
    # 2026-09-08 — typically well under its 5s timeout in practice), not a
    # measured guarantee — same caveat as PerplexityProvider.profile.
    profile = ProviderProfile(cost_per_query_usd=Decimal("0.000"), seconds_per_query=5.0)

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
        search_model: str = SEARCH_MODEL,
        extract_model: str = EXTRACT_MODEL,
    ):
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=timeout)
        self._search_model = search_model
        self._extract_model = extract_model
        # Exposes the search step's raw prose to callers that want it (e.g.
        # provider_eval.py's --keep-raw) without changing find_cheapest's
        # return type or signature. Reset at the start of every call, then
        # set from whatever _search actually returned — including None when
        # the search step produced no usable content — so a caller reading
        # it right after find_cheapest() always sees THIS call's result, not
        # a stale value from a previous product.
        self.last_search_text: str | None = None

    def find_cheapest(
        self, product: Product, market: str, max_delivery_days: int
    ) -> OfferResult | None:
        self.last_search_text = None
        search_text, citations = self._search(product, market, max_delivery_days)
        self.last_search_text = search_text
        if not search_text:
            return None
        return self._extract(search_text, citations, max_delivery_days)

    def _search(
        self, product: Product, market: str, max_delivery_days: int
    ) -> tuple[str | None, tuple[str, ...]]:
        request_body: dict = {
            "model": self._search_model,
            "messages": [
                {"role": "user", "content": self._build_search_prompt(product, market, max_delivery_days)}
            ],
            "max_tokens": SEARCH_MAX_TOKENS,
        }
        country = MARKET_COUNTRY_NAMES.get(market)
        if country is not None:
            # "boosts" (per Groq's docs), doesn't restrict, results toward
            # this country — free server-side ranking help. Omitted entirely
            # for an unmapped market rather than sending a guessed value.
            request_body["search_settings"] = {"country": country}
        try:
            response = call_with_retry(lambda: self._client.post(
                API_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            ))
            response_json = response.json()
        except httpx.HTTPError as exc:
            logger.warning(
                "Groq search call failed transiently for product %r: %s", product.name, exc,
            )
            raise ProviderUnavailable(str(exc)) from exc
        except json.JSONDecodeError:
            return None, ()

        try:
            message = response_json["choices"][0]["message"]
            content = message["content"]
        except (KeyError, IndexError, TypeError):
            return None, ()

        # executed_tools is absent entirely (not an empty list) when the
        # model answered without calling web search at all.
        executed_tools = message.get("executed_tools") or []
        urls: list[str] = []
        for tool in executed_tools:
            # search_results is an OBJECT with a "results" key (verified against
            # the published groq SDK's type definitions,
            # groq/types/chat/chat_completion_message.py:
            # ExecutedTool.search_results: Optional[ExecutedToolSearchResults],
            # where ExecutedToolSearchResults.results: Optional[List[...]]) —
            # NOT a bare list, despite how the prose docs read. Also absent
            # entirely (None) when the tool call found nothing.
            search_results = tool.get("search_results") or {}
            for result in search_results.get("results") or []:
                url = result.get("url")
                if isinstance(url, str) and url not in urls:
                    urls.append(url)
        return content, tuple(urls)

    def _extract(
        self, search_text: str, citations: tuple[str, ...], max_delivery_days: int
    ) -> OfferResult | None:
        try:
            response = call_with_retry(lambda: self._client.post(
                API_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._extract_model,
                    "messages": [
                        {"role": "user", "content": self._build_extract_prompt(search_text, max_delivery_days)}
                    ],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {"name": "cheapest_offer", "schema": RESPONSE_SCHEMA},
                    },
                    "max_tokens": EXTRACT_MAX_TOKENS,
                    "reasoning_effort": EXTRACT_REASONING_EFFORT,
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

        offer = validate_offer_fields(
            parsed, raw_response=raw_response, citations=citations,
            max_delivery_days=max_delivery_days,
        )
        if offer is not None and is_confirmed_dead(offer.source_url, self._client):
            return None
        return offer

    def _build_search_prompt(self, product: Product, market: str, max_delivery_days: int) -> str:
        # "in the {market} market" (the original wording) was observed live
        # to make the model reject sellers based outside that country even
        # when they explicitly ship there within the deadline — e.g. it
        # found a German seller with a Poland-shipping offer for a product
        # and still answered "no genuine PL-market offer" because the
        # seller itself wasn't Polish. The seller's location was never the
        # actual requirement; "can this buyer receive it in time" is.
        ean_part = f" (EAN: {product.ean})" if product.ean else ""
        return (
            f'Find the cheapest real, currently-buyable offer for "{product.name}"{ean_part}, '
            f"deliverable to a buyer in {market} within {max_delivery_days} days — seller can be "
            f"based anywhere, as long as it ships to {market} in time. Report price, currency, "
            f"seller name, exact source URL, and delivery time to {market}. If no genuine current "
            f"offer qualifies, say so explicitly rather than guessing."
        )

    def _build_extract_prompt(self, search_text: str, max_delivery_days: int) -> str:
        return (
            "Extract the cheapest offer described below into the requested JSON schema. "
            "The text may describe a page that is no longer available (a 404 / \"page not "
            "found\" result, or a page whose own content says the product wasn't found), a "
            "listing explicitly marked out of stock, backordered, discontinued, or withdrawn "
            "from sale (e.g. \"wycofane z oferty\", \"niedostępny\", \"out of stock\"), or a "
            "price-comparison or deal-aggregator page reporting another site's price rather "
            "than the seller's own listing. None of these count as a genuine, currently-"
            'buyable offer — set "found" to false rather than extracting a price from one, '
            "even if a price is shown.\n\n"
            f'Set "found" to false if the text does not describe a genuine current offer, or if '
            f"the only offer described has delivery_days greater than {max_delivery_days}.\n\n"
            f"Text:\n{search_text}"
        )
