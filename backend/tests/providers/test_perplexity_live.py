import os
from decimal import Decimal

import pytest

from app.models.product import Product
from app.providers.perplexity import PerplexityProvider

pytestmark = pytest.mark.skipif(
    not os.environ.get("PERPLEXITY_API_KEY"),
    reason="PERPLEXITY_API_KEY not set — export it to run this opt-in, cost-incurring smoke test",
)


def test_find_cheapest_returns_a_contract_valid_result_or_none():
    provider = PerplexityProvider(api_key=os.environ["PERPLEXITY_API_KEY"])
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
