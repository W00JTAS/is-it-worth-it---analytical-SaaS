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
