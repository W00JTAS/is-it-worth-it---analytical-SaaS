import os
from decimal import Decimal

import pytest

from app.models.product import Product
from app.providers.groq import GroqProvider

pytestmark = pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY"),
    reason="GROQ_API_KEY not set — export it to run this opt-in smoke test",
)


def test_find_cheapest_returns_a_contract_valid_result_or_none():
    provider = GroqProvider(api_key=os.environ["GROQ_API_KEY"])
    product = Product(
        tenant_id="default", source="csv", external_id="smoke-1", variant_id=None,
        name="Apple iPhone 15 128GB", ean="0195949037748",
        wholesale_price=Decimal("3000.00"), currency="PLN", category="Elektronika",
    )

    offer = provider.find_cheapest(product, market="PL", max_delivery_days=5)

    if offer is None:
        return  # a clean "no valid offer found" is an acceptable real-world outcome

    assert offer.source_url.startswith("http")
    assert 0.0 <= offer.confidence <= 1.0
    assert offer.price > 0
    assert offer.delivery_days <= 5
    assert offer.currency
    assert offer.seller
