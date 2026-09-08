from app.providers.parsing import validate_offer_fields


def test_returns_none_when_not_a_dict():
    assert validate_offer_fields(
        "not a dict", raw_response="{}", citations=(), max_delivery_days=5
    ) is None


def test_returns_none_when_not_found():
    assert validate_offer_fields(
        {"found": False}, raw_response="{}", citations=(), max_delivery_days=5
    ) is None


def test_returns_offer_for_valid_input():
    parsed = {
        "found": True, "price": 89.99, "currency": "PLN", "seller": "Example Shop",
        "source_url": "https://example.com/product", "delivery_days": 2, "confidence": 0.85,
    }

    offer = validate_offer_fields(
        parsed, raw_response="{}", citations=("https://example.com/product",),
        max_delivery_days=5,
    )

    assert offer is not None
    assert offer.price.__class__.__name__ == "Decimal"
    assert str(offer.price) == "89.99"
    assert offer.currency == "PLN"
    assert offer.seller == "Example Shop"
    assert offer.source_url == "https://example.com/product"
    assert offer.delivery_days == 2
    assert offer.confidence == 0.85
    assert offer.citations == ("https://example.com/product",)
    assert offer.raw_response == "{}"


def test_returns_none_when_delivery_exceeds_limit():
    parsed = {
        "found": True, "price": 10.0, "currency": "PLN", "seller": "X",
        "source_url": "https://example.com/x", "delivery_days": 20, "confidence": 0.9,
    }
    assert validate_offer_fields(
        parsed, raw_response="{}", citations=(), max_delivery_days=5
    ) is None


def test_returns_none_when_confidence_out_of_range():
    parsed = {
        "found": True, "price": 10.0, "currency": "PLN", "seller": "X",
        "source_url": "https://example.com/x", "delivery_days": 2, "confidence": 1.5,
    }
    assert validate_offer_fields(
        parsed, raw_response="{}", citations=(), max_delivery_days=5
    ) is None


def test_normalizes_zloty_symbol_to_iso_code():
    parsed = {
        "found": True, "price": 108.34, "currency": "zł", "seller": "X",
        "source_url": "https://example.com/x", "delivery_days": 2, "confidence": 0.9,
    }
    offer = validate_offer_fields(
        parsed, raw_response="{}", citations=(), max_delivery_days=5
    )
    assert offer is not None
    assert offer.currency == "PLN"


def test_normalizes_lowercase_iso_code_to_uppercase():
    parsed = {
        "found": True, "price": 10.0, "currency": "pln", "seller": "X",
        "source_url": "https://example.com/x", "delivery_days": 2, "confidence": 0.9,
    }
    offer = validate_offer_fields(
        parsed, raw_response="{}", citations=(), max_delivery_days=5
    )
    assert offer is not None
    assert offer.currency == "PLN"


def test_normalizes_euro_and_dollar_symbols():
    for symbol, iso in (("€", "EUR"), ("$", "USD"), ("£", "GBP")):
        parsed = {
            "found": True, "price": 10.0, "currency": symbol, "seller": "X",
            "source_url": "https://example.com/x", "delivery_days": 2, "confidence": 0.9,
        }
        offer = validate_offer_fields(
            parsed, raw_response="{}", citations=(), max_delivery_days=5
        )
        assert offer is not None
        assert offer.currency == iso


def test_rejects_known_price_comparison_aggregator_domains():
    # Regression for a live eval run (2026-09-08): despite an explicit prompt
    # instruction to prefer the actual seller's page over a price-comparison
    # site, GroqProvider/FirecrawlProvider still confidently extracted
    # ceneo.pl and skapiec.pl comparison pages as source_url in 3/23 found
    # offers — one of them (skapiec.pl) with a price that matched nothing on
    # the actual cited page (fabricated). A prose instruction is not reliable
    # enough here; a domain check is deterministic. See
    # .claude/rules/groq-firecrawl-offer-validity-audit.md's 2026-09-08 update.
    for url in (
        "https://www.ceneo.pl/100716985?srsltid=abc",
        "https://www.skapiec.pl/site/cat/8/comp/882235706",
        "http://skapiec.pl/foo",
    ):
        parsed = {
            "found": True, "price": 10.0, "currency": "PLN", "seller": "X",
            "source_url": url, "delivery_days": 2, "confidence": 0.9,
        }
        assert validate_offer_fields(
            parsed, raw_response="{}", citations=(), max_delivery_days=5
        ) is None, url


def test_does_not_reject_a_direct_seller_domain():
    parsed = {
        "found": True, "price": 10.0, "currency": "PLN", "seller": "X",
        "source_url": "https://www.x-kom.pl/p/12345.html", "delivery_days": 2, "confidence": 0.9,
    }
    assert validate_offer_fields(
        parsed, raw_response="{}", citations=(), max_delivery_days=5
    ) is not None
