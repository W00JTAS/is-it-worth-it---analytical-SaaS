# Phase 6: `ShopifySource` sketch — design

Full project rationale: `docs/superpowers/specs/2026-07-28-is-it-worth-it-design.md`, line 168 —
"Szkic `ShopifySource` (weryfikacja abstrakcji, bez OAuth/hostingu)". This is the only remaining
open phase; the whole-site impeccable audit that blocked it is closed (see handoff 8).

## Goal

Find out whether the existing `CatalogSource` protocol (`backend/app/sources/base.py`) survives
contact with a real second source, before more of the pipeline is built on top of it. Read-only,
no OAuth, no deployment, no hosting — a sketch, not a shippable Shopify integration.

**Definition of done**: a live integration test against a real Shopify dev store, containing at
least one multi-variant product, passes and produces correctly-mapped `Product` objects — proving
`CatalogSource.fetch_products() -> Iterable[Product]` needed zero signature changes. If it *didn't*
survive unchanged, this doc gets updated to record exactly what had to give.

## Decisions

- **Auth**: a custom-app Admin API access token (Shopify Admin → Apps → develop apps → create a
  custom app scoped to `read_products`), passed via `X-Shopify-Access-Token` header. No OAuth flow
  — matches the spec's explicit constraint.
- **API**: GraphQL Admin API, not REST. REST Admin API is a legacy API as of October 1, 2024 and is
  in maintenance mode only, per Shopify's own migration guide
  (`shopify.dev/docs/apps/build/graphql/migrate`, fetched 2026-08-26) — building new code on REST
  now would be building on a dead end. Default API version: `2026-07` (current stable per
  `shopify.dev/docs/api/admin-graphql`, fetched 2026-08-26), passed as a constructor parameter so
  it isn't silently pinned to a version that will eventually sunset.
- **Test target**: a real Shopify Partners dev store (free), not fixtures-only — the point of a
  "sketch" per the parent spec is proving contact with the *real* API, not just this project's
  assumptions about its shape. Needs setting up (Partners account → dev store → custom app →
  access token) before the live test can run.

## Component

`backend/app/sources/shopify_source.py` — `ShopifyCatalogSource`, implementing the existing
`CatalogSource` Protocol with no changes to the protocol itself (that's a finding either way).

```python
class ShopifyCatalogSource:
    SOURCE_NAME = "shopify"

    def __init__(
        self,
        shop_domain: str,       # e.g. "my-dev-store.myshopify.com"
        access_token: str,
        tenant_id: str,
        client: httpx.Client | None = None,
        api_version: str = "2026-07",
    ) -> None: ...

    def fetch_products(self) -> list[Product]: ...
```

Constructor shape mirrors `PerplexityProvider` (`backend/app/providers/perplexity.py`): an injected
`httpx.Client` for testability, following this repo's established pattern rather than introducing
a new one.

Endpoint: `POST https://{shop_domain}/admin/api/{api_version}/graphql.json`.

## Data flow / field mapping

One upfront query for the shop's currency:

```graphql
{ shop { currencyCode } }
```

Then a paginated query over products and their variants:

```graphql
query($cursor: String) {
  products(first: 50, after: $cursor) {
    edges {
      cursor
      node {
        id
        title
        productType
        variants(first: 100) {
          edges { node { id title price barcode } }
        }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
```

Looping on `pageInfo.hasNextPage`/`endCursor` until exhausted. **Each variant becomes one
`Product`** — this is the actual test of the abstraction, since `variant_id` exists in the model
specifically to anticipate multi-variant sources that CSV never had:

| `Product` field | Shopify source | Notes |
|---|---|---|
| `tenant_id` | constructor arg | passed straight through, same as `CsvCatalogSource` |
| `source` | `"shopify"` | |
| `external_id` | product `id` (full GID, e.g. `gid://shopify/Product/123`) | kept as-is, not parsed — GIDs are already globally stable and unique |
| `variant_id` | variant `id` (full GID) | |
| `name` | `product.title` if variant `title == "Default Title"`, else `f"{product.title} - {variant.title}"` | needed once a product has real variants (size/color) — otherwise two rows would read identically in a report |
| `wholesale_price` | variant `price` (string) → `normalize.money.parse_price()` | the shop's listed price stands in for a supplier's wholesale cost — reusing the existing parser proves it's format-agnostic, not CSV-specific |
| `currency` | shop's `currencyCode`, queried once and reused for every product | |
| `ean` | variant `barcode` → `normalize.ean.is_valid_ean()` | invalid or missing barcode → `ean=None` + a warning, mirroring `CsvCatalogSource`'s handling |
| `category` | `product.productType`, or `"Bez kategorii"` if blank | matches the CSV source's existing fallback string exactly |

Skip rules mirror `CsvCatalogSource`: a variant with a missing/unparseable price, or a zero price,
is skipped with a warning appended to `self.warnings` (same `list[str]` convention). No EAN
deduplication logic is being ported over for this sketch — that was a CSV-specific reality (the
same product listed twice in a supplier's spreadsheet); a Shopify catalog doesn't have that failure
mode since each variant is already a unique row from the store's own database.

## Error handling

New `ShopifyApiError(Exception)` in `shopify_source.py`, mirroring `EmptyCsvError`'s pattern —
raised when:
- the HTTP response status is not 200, or
- the GraphQL response body contains a top-level `errors` array.

No retry/backoff logic, no handling of Shopify's GraphQL cost-based rate limiting (`THROTTLED`
errors) — explicitly out of scope for a read-only sketch whose job is proving the data shape, not
production resilience.

## Testing

Two files, following this repo's existing naming and mocking conventions exactly
(`tests/providers/test_perplexity.py` / `test_perplexity_live.py`):

- **`tests/sources/test_shopify_source.py`** — unit tests against hand-written GraphQL response
  fixtures, using the same duck-typed `_FakeClient`/`_FakeResponse` pattern as
  `test_perplexity.py` (not `httpx.MockTransport`, which isn't used anywhere in this codebase).
  Cases: a single page of products, pagination across two pages, a product with 3 variants, a
  variant with a missing/invalid barcode, a variant whose title is `"Default Title"` vs. a real
  variant title, a zero-price variant (skipped + warned), a non-200 HTTP response and a GraphQL
  `errors` payload (both raise `ShopifyApiError`).
- **`tests/sources/test_shopify_source_live.py`** — one smoke test against the real dev store,
  gated exactly like `test_perplexity_live.py`:
  ```python
  pytestmark = pytest.mark.skipif(
      not (os.environ.get("SHOPIFY_TEST_SHOP") and os.environ.get("SHOPIFY_TEST_TOKEN")),
      reason="SHOPIFY_TEST_SHOP/SHOPIFY_TEST_TOKEN not set — export them to run this opt-in test",
  )
  ```
  Never runs in default `pytest`/CI. Asserts `fetch_products()` returns a non-empty list, at least
  one product has `variant_id` set, and every returned `Product` has a positive `wholesale_price`
  and a non-empty `currency`.

## Non-goals (explicit)

No OAuth or app installation flow, no webhooks (including the GDPR-mandatory ones a real Shopify
app requires), no `CatalogSink` write-back, no rate-limit backoff, no multi-shop/tenant management
beyond passing `tenant_id` straight through, no UI. All of this is already listed as out-of-scope
for V1 in the parent design spec's "Świadomie poza zakresem V1" section — restated here so this
phase doesn't silently grow past what it's meant to prove.

## Setup required before the live test can run

1. Create a free Shopify Partners account (partners.shopify.com) if one doesn't exist yet.
2. Create a development store under that account.
3. In the dev store admin: Settings → Apps and sales channels → Develop apps → create a custom
   app, grant it the `read_products` scope, install it, and copy its Admin API access token.
4. Manually create at least one product with 2+ variants in the dev store (a fresh dev store ships
   empty), so the live test actually exercises the `variant_id`-per-variant mapping.
5. Export `SHOPIFY_TEST_SHOP=<store>.myshopify.com` and `SHOPIFY_TEST_TOKEN=<token>` before running
   `pytest tests/sources/test_shopify_source_live.py`.

This setup is manual, one-time, and outside the implementation plan's task breakdown — it's a
prerequisite for step 5, not a coding task.
