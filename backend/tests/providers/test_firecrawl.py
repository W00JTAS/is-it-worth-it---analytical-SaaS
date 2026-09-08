import json
from decimal import Decimal

import httpx
import pytest

from app.models.product import Product
from app.providers.base import ProviderAuthError, ProviderRateLimited, ProviderUnavailable
from app.providers.firecrawl import SEARCH_API_URL, FirecrawlProvider
from app.providers.groq import API_URL as GROQ_API_URL
from app.providers.groq import EXTRACT_MAX_TOKENS, EXTRACT_REASONING_EFFORT


def _make_product(**overrides) -> Product:
    defaults = dict(
        tenant_id="t1", source="csv", external_id="1", variant_id=None,
        name="Test Product", ean="5901234123457",
        wholesale_price=Decimal("60.00"), currency="PLN", category="Test",
    )
    defaults.update(overrides)
    return Product(**defaults)


def _search_response(web: list[dict] | None) -> dict:
    data = {"web": web} if web is not None else {}
    return {"success": True, "data": data, "creditsUsed": 2}


def _extract_response(parsed: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(parsed)}}]}


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200, headers: dict | None = None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


class _TwoServiceClient:
    """Returns `search_payload` for the Firecrawl search call, `extract_payload`
    for the Groq extraction call, distinguishing by URL — the two providers
    hit different hosts entirely. Also answers the post-extraction liveness
    check's `.head()` call — defaults to 200 (alive) so tests that don't
    care about liveness are unaffected."""

    def __init__(self, search_payload: dict, extract_payload: dict, link_status_code: int = 200):
        self._search_payload = search_payload
        self._extract_payload = extract_payload
        self._link_status_code = link_status_code
        self.requests: list[dict] = []
        self.head_requests: list[str] = []

    def post(self, url, headers, json):
        self.requests.append({"url": url, "headers": headers, "json": json})
        if url == SEARCH_API_URL:
            return _FakeResponse(self._search_payload)
        return _FakeResponse(self._extract_payload)

    def head(self, url, timeout=None, follow_redirects=None):
        self.head_requests.append(url)
        return _FakeResponse({}, status_code=self._link_status_code)


def test_two_call_flow_returns_offer_with_citations_from_search_results():
    client = _TwoServiceClient(
        search_payload=_search_response([
            {"title": "Example Shop", "description": "Cena: 89.99 zl", "url": "https://example.com/product", "position": 1},
        ]),
        extract_payload=_extract_response({
            "found": True, "price": 89.99, "currency": "PLN", "seller": "Example Shop",
            "source_url": "https://example.com/product", "delivery_days": 2, "confidence": 0.85,
        }),
    )
    provider = FirecrawlProvider(api_key="fc-key", groq_api_key="groq-key", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer is not None
    assert offer.price == Decimal("89.99")
    assert offer.citations == ("https://example.com/product",)
    assert client.requests[0]["url"] == SEARCH_API_URL
    assert client.requests[1]["url"] == GROQ_API_URL
    assert client.requests[1]["json"]["response_format"]["type"] == "json_schema"


def test_uses_correct_bearer_key_on_each_call():
    client = _TwoServiceClient(
        search_payload=_search_response([{"title": "t", "description": "d", "url": "https://example.com/x"}]),
        extract_payload=_extract_response({"found": False}),
    )
    provider = FirecrawlProvider(api_key="firecrawl-secret", groq_api_key="groq-secret", client=client)

    provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert client.requests[0]["headers"]["Authorization"] == "Bearer firecrawl-secret"
    assert client.requests[1]["headers"]["Authorization"] == "Bearer groq-secret"


def test_ean_first_query_when_ean_present():
    client = _TwoServiceClient(
        search_payload=_search_response([]),
        extract_payload=_extract_response({"found": False}),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    provider.find_cheapest(
        _make_product(ean="5901234123457", name="Widget"), market="PL", max_delivery_days=5,
    )

    assert client.requests[0]["json"]["query"] == "5901234123457 Widget cena zł"


def test_name_only_query_when_ean_absent():
    client = _TwoServiceClient(
        search_payload=_search_response([]),
        extract_payload=_extract_response({"found": False}),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    provider.find_cheapest(_make_product(ean=None, name="Widget"), market="PL", max_delivery_days=5)

    assert client.requests[0]["json"]["query"] == "Widget cena zł"


def test_location_present_for_mapped_market():
    client = _TwoServiceClient(
        search_payload=_search_response([]),
        extract_payload=_extract_response({"found": False}),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert client.requests[0]["json"]["location"] == "Poland"


def test_location_absent_for_unmapped_market():
    client = _TwoServiceClient(
        search_payload=_search_response([]),
        extract_payload=_extract_response({"found": False}),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    provider.find_cheapest(_make_product(), market="XX", max_delivery_days=5)

    assert "location" not in client.requests[0]["json"]


def test_shopping_term_appended_for_mapped_market():
    client = _TwoServiceClient(
        search_payload=_search_response([]),
        extract_payload=_extract_response({"found": False}),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    provider.find_cheapest(
        _make_product(ean=None, name="Widget"), market="PL", max_delivery_days=5,
    )

    assert client.requests[0]["json"]["query"] == "Widget cena zł"


def test_shopping_term_absent_for_unmapped_market():
    client = _TwoServiceClient(
        search_payload=_search_response([]),
        extract_payload=_extract_response({"found": False}),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    provider.find_cheapest(
        _make_product(ean=None, name="Widget"), market="XX", max_delivery_days=5,
    )

    assert client.requests[0]["json"]["query"] == "Widget"


def test_returns_none_and_skips_extraction_when_no_web_results():
    client = _TwoServiceClient(
        search_payload=_search_response([]),
        # If _extract were ever called with this payload, offer would be
        # truthy and the "no extraction call attempted" assertion would fail.
        extract_payload=_extract_response({
            "found": True, "price": 1.0, "currency": "PLN", "seller": "S",
            "source_url": "https://example.com", "delivery_days": 1, "confidence": 1.0,
        }),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer is None
    assert len(client.requests) == 1  # only the search call


def test_returns_none_and_skips_extraction_when_data_missing_web_key():
    client = _TwoServiceClient(
        search_payload={"success": True, "data": {}, "creditsUsed": 0},
        extract_payload=_extract_response({
            "found": True, "price": 1.0, "currency": "PLN", "seller": "S",
            "source_url": "https://example.com", "delivery_days": 1, "confidence": 1.0,
        }),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer is None
    assert len(client.requests) == 1


def test_dedupes_citation_urls_across_multiple_search_results():
    client = _TwoServiceClient(
        search_payload=_search_response([
            {"title": "A", "description": "d", "url": "https://example.com/x"},
            {"title": "B", "description": "d", "url": "https://example.com/x"},
            {"title": "C", "description": "d", "url": "https://example.com/y"},
        ]),
        extract_payload=_extract_response({
            "found": True, "price": 5.0, "currency": "PLN", "seller": "S",
            "source_url": "https://example.com/x", "delivery_days": 1, "confidence": 0.5,
        }),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer.citations == ("https://example.com/x", "https://example.com/y")


def test_extract_prompt_includes_search_snippet_text():
    client = _TwoServiceClient(
        search_payload=_search_response([
            {"title": "Example Shop", "description": "Cena: 89.99 zl", "url": "https://example.com/product"},
        ]),
        extract_payload=_extract_response({"found": False}),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    prompt = client.requests[1]["json"]["messages"][0]["content"]
    assert "Example Shop" in prompt
    assert "89.99" in prompt
    assert "https://example.com/product" in prompt


def test_extract_prompt_warns_against_secondary_upsell_prices():
    # Regression for a price-bleed bug found in a 2026-09-02 live eval run:
    # a genuine single-product-page snippet can still contain a second, much
    # smaller price for an accessory/upsell (e.g. "Kupując ten produkt..."),
    # and the extraction model picked that one instead of the product's own
    # price even though the URL was correctly scoped to this exact product —
    # the earlier source_url-specificity fix only catches category/search
    # pages, not this case. The prompt must instruct the model to cross-check
    # a candidate price against the other results' price range.
    client = _TwoServiceClient(
        search_payload=_search_response([
            {"title": "Example Shop", "description": "Cena: 89.99 zl", "url": "https://example.com/product"},
        ]),
        extract_payload=_extract_response({"found": False}),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    prompt = client.requests[1]["json"]["messages"][0]["content"]
    assert "accessory" in prompt.lower()
    assert "dramatically below all of them" in prompt.lower()
    assert "OTHER results" in prompt
    assert "drifts partway through" in prompt.lower()


def test_extract_prompt_warns_against_title_description_variant_mismatch():
    # Regression for a live eval finding (2026-09-08): a result titled
    # "...unisex różowe" (pink) had a description whose price sentence
    # actually named a different color ("...unisex żółte", yellow) — the
    # existing "drifts partway through into a different product" language
    # didn't stop the model using that price under the pink result's URL.
    # The prompt must tell the model to compare the result's own title
    # variant against its description's variant explicitly.
    client = _TwoServiceClient(
        search_payload=_search_response([
            {"title": "Example Shop", "description": "Cena: 89.99 zl", "url": "https://example.com/product"},
        ]),
        extract_payload=_extract_response({"found": False}),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    prompt = client.requests[1]["json"]["messages"][0]["content"].lower()
    assert "title" in prompt and "description" in prompt
    assert "different variant named in the description" in prompt


def test_extract_prompt_carries_the_searched_for_product_name():
    # Regression for a structural gap found 2026-09-08: _extract never
    # received the product being searched for at all, only raw search
    # snippets — so it had no ground truth to check a candidate result's
    # color/size/pack-quantity against. Two live-confirmed bugs followed: a
    # gray beanbag resolved to a brown one, and a single-can food price
    # resolved to a 12-pack listing. The extraction prompt must name the
    # exact product being searched for and instruct rejecting a result whose
    # own title/description names a different variant of it.
    client = _TwoServiceClient(
        search_payload=_search_response([
            {"title": "Example Shop", "description": "Cena: 89.99 zl", "url": "https://example.com/product"},
        ]),
        extract_payload=_extract_response({"found": False}),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    provider.find_cheapest(
        _make_product(name="Pufa worek sako KOTEK szary XL 130x90"),
        market="PL", max_delivery_days=5,
    )

    prompt = client.requests[1]["json"]["messages"][0]["content"]
    assert "Pufa worek sako KOTEK szary XL 130x90" in prompt
    assert "pack" in prompt.lower() or "quantity" in prompt.lower()


def test_extract_prompt_carries_market_and_deliverability_requirement():
    # Regression for the reviewer's Important finding: `market` reached
    # `_search` (for the location boost) but never `_extract`'s prompt, so
    # the extraction model had no deliverability or market context at all —
    # risking a valid-looking OfferResult for an offer that doesn't actually
    # ship to the target market, or in a currency the caller doesn't expect
    # (the worst class of money bug: a wrong number produced silently,
    # not an error).
    client = _TwoServiceClient(
        search_payload=_search_response([
            {"title": "Example Shop", "description": "Cena: 89.99 zl", "url": "https://example.com/product"},
        ]),
        extract_payload=_extract_response({"found": False}),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    prompt = client.requests[1]["json"]["messages"][0]["content"]
    assert "PL" in prompt
    assert "5 days" in prompt  # max_delivery_days threaded through
    assert "seller can be based anywhere" in prompt  # not a seller-location requirement


def test_extract_prompt_clamps_default_delivery_days_to_max_delivery_days():
    # At a tight max_delivery_days (below the generic 3-day fallback), the
    # fallback used for an unstated delivery time must not itself exceed the
    # caller's ceiling, or validate_offer_fields would reject every
    # unstated-delivery-time offer outright.
    client = _TwoServiceClient(
        search_payload=_search_response([
            {"title": "Example Shop", "description": "89.99 zl", "url": "https://example.com/product"},
        ]),
        extract_payload=_extract_response({"found": False}),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    provider.find_cheapest(_make_product(), market="PL", max_delivery_days=1)

    prompt = client.requests[1]["json"]["messages"][0]["content"]
    assert "use 1 as a conservative default" in prompt


def test_extract_prompt_rejects_dead_and_unavailable_listings():
    # Regression for the 2026-09-08 offer-validity audit: a live audit of
    # a real scan found confidently-reported offers (confidence >= 0.80) for
    # 404 pages, soft-404 "product not found" pages, discontinued/out-of-
    # stock listings, and a deal-aggregator page rather than the seller's
    # own listing. The existing "never a search-results/category/comparison
    # page" instruction didn't stop the aggregator case in practice, so this
    # spells out the aggregator rejection explicitly too, alongside
    # liveness/stock status which had no prompt coverage at all before.
    client = _TwoServiceClient(
        search_payload=_search_response([
            {"title": "Example Shop", "description": "Cena: 89.99 zl", "url": "https://example.com/product"},
        ]),
        extract_payload=_extract_response({"found": False}),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    prompt = client.requests[1]["json"]["messages"][0]["content"].lower()
    assert "out of stock" in prompt
    assert "discontinued" in prompt
    assert "404" in prompt
    assert "aggregator" in prompt


def test_rejects_offer_when_source_url_is_confirmed_dead():
    # A search snippet can be stale — the page it was indexed from has since
    # gone away — with nothing in the cached text to reveal that, so no
    # prompt instruction can catch it (2026-09-08 offer-validity audit).
    # A live HEAD check against source_url is the only way.
    client = _TwoServiceClient(
        search_payload=_search_response([
            {"title": "Example Shop", "description": "Cena: 89.99 zl", "url": "https://example.com/gone"},
        ]),
        extract_payload=_extract_response({
            "found": True, "price": 89.99, "currency": "PLN", "seller": "Example Shop",
            "source_url": "https://example.com/gone", "delivery_days": 2, "confidence": 0.85,
        }),
        link_status_code=404,
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer is None
    assert client.head_requests == ["https://example.com/gone"]


def test_keeps_offer_when_source_url_liveness_check_is_inconclusive():
    # A 403 (bot-block, extremely common on Allegro and similar gated
    # marketplaces) must never be treated as dead — only a confirmed 404
    # rejects an offer.
    client = _TwoServiceClient(
        search_payload=_search_response([
            {"title": "Example Shop", "description": "Cena: 89.99 zl", "url": "https://allegro.pl/produkt/x"},
        ]),
        extract_payload=_extract_response({
            "found": True, "price": 89.99, "currency": "PLN", "seller": "Example Shop",
            "source_url": "https://allegro.pl/produkt/x", "delivery_days": 2, "confidence": 0.85,
        }),
        link_status_code=403,
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    offer = provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert offer is not None
    assert offer.price == Decimal("89.99")


def test_extract_call_includes_max_tokens_and_reasoning_effort():
    client = _TwoServiceClient(
        search_payload=_search_response([
            {"title": "Example Shop", "description": "89.99 PLN", "url": "https://example.com/product"},
        ]),
        extract_payload=_extract_response({"found": False}),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    extract_body = client.requests[1]["json"]
    assert extract_body["max_tokens"] == EXTRACT_MAX_TOKENS
    assert extract_body["reasoning_effort"] == EXTRACT_REASONING_EFFORT


def test_extract_model_constructor_override_is_used_in_extract_call():
    client = _TwoServiceClient(
        search_payload=_search_response([
            {"title": "Example Shop", "description": "89.99 PLN", "url": "https://example.com/product"},
        ]),
        extract_payload=_extract_response({
            "found": True, "price": 89.99, "currency": "PLN", "seller": "Example Shop",
            "source_url": "https://example.com/product", "delivery_days": 2, "confidence": 0.85,
        }),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client, extract_model="custom-model")

    provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert client.requests[1]["json"]["model"] == "custom-model"


class _SearchCallFailsClient:
    def post(self, url, headers, json):
        raise httpx.ConnectError("connection refused")


def test_raises_provider_unavailable_when_search_call_fails():
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=_SearchCallFailsClient())

    with pytest.raises(ProviderUnavailable):
        provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)


class _AuthFailsOnSearchClient:
    def post(self, url, headers, json):
        return _FakeResponse({}, status_code=401)


def test_raises_provider_auth_error_when_search_call_rejects_key():
    provider = FirecrawlProvider(api_key="bad-key", groq_api_key="g", client=_AuthFailsOnSearchClient())

    with pytest.raises(ProviderAuthError):
        provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)


class _AuthFailsOnExtractClient:
    def post(self, url, headers, json):
        if url == SEARCH_API_URL:
            return _FakeResponse(_search_response([
                {"title": "t", "description": "d", "url": "https://example.com/x"},
            ]))
        return _FakeResponse({}, status_code=401)


def test_raises_provider_auth_error_when_extract_call_rejects_key():
    provider = FirecrawlProvider(api_key="k", groq_api_key="bad-key", client=_AuthFailsOnExtractClient())

    with pytest.raises(ProviderAuthError):
        provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)


def test_raises_provider_rate_limited_after_exhausting_retries_on_search(monkeypatch):
    monkeypatch.setattr("app.providers.retry.time.sleep", lambda *_: None)

    class _AlwaysRateLimitedClient:
        def post(self, url, headers, json):
            return _FakeResponse({}, status_code=429)

    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=_AlwaysRateLimitedClient())

    with pytest.raises(ProviderRateLimited):
        provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)


def test_raises_provider_unavailable_when_body_reports_success_false():
    # Firecrawl reports its own failures in-band: HTTP 200 with
    # "success": false. Nothing else in the module reads `success`, so
    # without an explicit check this falls through to the data.web lookup,
    # comes back empty, and is misreported as a legitimate `None` — which
    # base.py's contract says is safe to persist as a negative cache entry.
    client = _TwoServiceClient(
        search_payload={"success": False, "error": "insufficient credits"},
        extract_payload=_extract_response({"found": False}),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    with pytest.raises(ProviderUnavailable) as exc_info:
        provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert "insufficient credits" in str(exc_info.value)
    assert len(client.requests) == 1  # no extraction call attempted


def test_success_false_without_a_recognised_error_field_still_raises():
    # Defensive: the exact error field on a failed v2/search response isn't
    # confirmed against a live failure, so an unrecognised body must still
    # raise ProviderUnavailable rather than crash on a missing key.
    client = _TwoServiceClient(
        search_payload={"success": False, "somethingElse": 42},
        extract_payload=_extract_response({"found": False}),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    with pytest.raises(ProviderUnavailable):
        provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)


def test_success_true_with_empty_results_is_still_a_legitimate_none():
    # Guard against over-correcting finding #6: only an explicit
    # success:false is an unavailability. A successful search that genuinely
    # found nothing must stay a cacheable None.
    client = _TwoServiceClient(
        search_payload=_search_response([]),
        extract_payload=_extract_response({"found": False}),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    assert provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5) is None


class _GarbageExtractClient:
    """Search succeeds; the extraction call returns a structurally wrong
    envelope (no choices) — unparseable garbage, not a model verdict."""

    def post(self, url, headers, json):
        if url == SEARCH_API_URL:
            return _FakeResponse(_search_response([
                {"title": "t", "description": "d", "url": "https://example.com/x"},
            ]))
        return _FakeResponse({"unexpected": "shape"})


def test_raises_provider_unavailable_on_unparseable_extraction_envelope():
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=_GarbageExtractClient())

    with pytest.raises(ProviderUnavailable):
        provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)


class _NonJsonExtractContentClient:
    """Search succeeds; the extraction model's `content` isn't JSON at all."""

    def post(self, url, headers, json):
        if url == SEARCH_API_URL:
            return _FakeResponse(_search_response([
                {"title": "t", "description": "d", "url": "https://example.com/x"},
            ]))
        return _FakeResponse({"choices": [{"message": {"content": "I'm sorry, I cannot"}}]})


def test_raises_provider_unavailable_when_extraction_content_is_not_json():
    provider = FirecrawlProvider(
        api_key="k", groq_api_key="g", client=_NonJsonExtractContentClient(),
    )

    with pytest.raises(ProviderUnavailable):
        provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)


class _NoFoundKeyExtractClient:
    def post(self, url, headers, json):
        if url == SEARCH_API_URL:
            return _FakeResponse(_search_response([
                {"title": "t", "description": "d", "url": "https://example.com/x"},
            ]))
        return _FakeResponse(_extract_response({"price": 10.0, "currency": "PLN"}))


def test_raises_provider_unavailable_when_extraction_json_lacks_found_key():
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=_NoFoundKeyExtractClient())

    with pytest.raises(ProviderUnavailable):
        provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)


def test_legitimate_found_false_extraction_still_returns_none_not_unavailable():
    # The case that must NOT regress: a well-formed schema object where the
    # model said "no offer" is a genuine negative result, safe to cache.
    client = _TwoServiceClient(
        search_payload=_search_response([
            {"title": "t", "description": "d", "url": "https://example.com/x"},
        ]),
        extract_payload=_extract_response({"found": False}),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    assert provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5) is None


def test_last_search_text_records_snippets_seen_by_extraction():
    client = _TwoServiceClient(
        search_payload=_search_response([
            {"title": "Example Shop", "description": "Cena: 89.99 zl", "url": "https://example.com/product"},
        ]),
        extract_payload=_extract_response({"found": False}),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)

    assert provider.last_search_text is None  # nothing called yet

    provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)

    assert provider.last_search_text is not None
    assert "Example Shop" in provider.last_search_text
    assert "https://example.com/product" in provider.last_search_text
    # Exactly the block the extraction prompt embedded, so --keep-raw records
    # the material the extraction actually worked from.
    assert provider.last_search_text in client.requests[1]["json"]["messages"][0]["content"]


def test_last_search_text_is_set_before_the_early_return_on_no_results():
    # A not_found caused by an empty search must still be debuggable offline
    # — and must not leak the previous product's snippets.
    client = _TwoServiceClient(
        search_payload=_search_response([]),
        extract_payload=_extract_response({"found": False}),
    )
    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=client)
    provider.last_search_text = "stale text from a previous product"

    assert provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5) is None
    assert provider.last_search_text == ""


def test_raises_provider_rate_limited_after_exhausting_retries_on_extract(monkeypatch):
    monkeypatch.setattr("app.providers.retry.time.sleep", lambda *_: None)

    class _RateLimitedOnExtractClient:
        def post(self, url, headers, json):
            if url == SEARCH_API_URL:
                return _FakeResponse(_search_response([
                    {"title": "t", "description": "d", "url": "https://example.com/x"},
                ]))
            return _FakeResponse({}, status_code=429)

    provider = FirecrawlProvider(api_key="k", groq_api_key="g", client=_RateLimitedOnExtractClient())

    with pytest.raises(ProviderRateLimited):
        provider.find_cheapest(_make_product(), market="PL", max_delivery_days=5)
