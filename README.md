# IS_IT_WORTH_IT

A tool that answers one question for a dropshipping supplier's CSV catalog: **is it actually
worth it?** It takes a wholesale-price catalog, finds the cheapest real market offer for each
product (with a hard delivery-time filter — cheap offers shipping from the other side of the
world don't count), calculates margin against your own cost assumptions (commission, shipping,
VAT, returns), and produces a report: a verdict, a scenario matrix, and a per-product
drill-down.

V1 is a local, single-user web tool. A WooCommerce catalog source is implemented; a
Shopify source exists but is currently gated off pending a cost-aware rewrite (its GraphQL
query exceeds Shopify's per-request cost cap). Dedicated Shopify/WooCommerce *apps* (not
just catalog sources) are a future direction, not yet started.

## Try it without an API key

Three demo catalogs (25 products each — kitchen, toys, electronics) ship with the app and are
one click away on the upload screen, so the whole wizard — mapping, scope, cost estimate, report
layout — can be walked through with no key and no CSV of your own. Only the price-discovery step
itself calls a paid API.

```bash
cd backend && .venv/bin/uvicorn app.main:app --port 8000   # terminal 1
cd frontend && npm install && npm run dev                  # terminal 2
```

Then open `http://localhost:5173` and pick one of the demo catalogs.

## How it works

```
Upload → Mapping → Scope + Estimate → Progress → Report
```

1. **Upload** — pick a CSV catalog from your supplier.
2. **Mapping** — confirm (or fix) how the CSV's columns map to name / wholesale price / EAN /
   category. Auto-detected where possible; nothing here spends money.
3. **Scope + Estimate** — choose a full scan or a per-category sample, see the exact query
   count and USD cost *before* anything runs.
4. **Progress** — live progress while the price-discovery job runs.
5. **Report** — the verdict: average margin at the current price, a scenario matrix
   (−10%/−5%/0%/+5% around the market price), a per-category breakdown, and a paginated,
   filterable product drill-down with every offer's source link.

Full design rationale lives in `docs/superpowers/specs/2026-07-28-is-it-worth-it-design.md`.

## Architecture

```
CatalogSource → Normalize → Scope+Estimate → Price Discovery → Margin Engine → Report
  (CSV today)                                   ↕ Cache (SQLite)
```

- **Backend** (`backend/`) — Python + FastAPI. API-first: all domain logic (CSV parsing, EAN
  validation, price lookup, margin math) lives here, never in the frontend.
- **Frontend** (`frontend/`) — React 19 + TypeScript + Vite + Tailwind. A thin client over the
  backend API — no domain logic, no router, no data-fetching library.
- **Price discovery** — pluggable AI provider (`PROVIDER` env var): Perplexity Sonar
  (default, paid), Groq's free tier alone (`compound-mini` + `gpt-oss-20b`, two-call
  search-then-extract), or `groq+firecrawl` (Groq primary, falls back to Firecrawl once Groq's
  search step rate-limits — the two don't fully avoid sharing quota, since Firecrawl's own
  extraction step still calls Groq's extraction model). Measured found-rates are in
  [Measured provider quality](#measured-provider-quality) below; the free tier is demo-scale
  only, not sized for a full catalog scan. A SQLite cache
  keyed on `(ean, market, provider, max_delivery_days)` means you never pay twice for the same
  lookup, shared across whichever provider is active.
- **Money** — always `Decimal`, never `float`, end to end.

## Measured provider quality

Found-rate is the share of catalog products for which a provider returns a usable market offer.
It was measured on two fixed, seeded 25-product samples drawn from a real 115k-row supplier
catalog, with the raw responses stored so prompt changes could be replayed without re-querying:

| Provider | Sample | Found | Not found | Error (rate-limit) | Found-rate |
|---|---|---|---|---|---|
| `groq` alone | various | — | — | high | 8–32% |
| `groq+firecrawl` | tuning (seed=42) | 21 | 2 | 2 | **84%** |
| `groq+firecrawl` | hold-out (seed=7) | 16 | 2 | 7 | **64%** raw, 89% of completed |

The 20-point gap between the tuning sample and a fresh hold-out is the honest headline: prompt
tuning measured only on the sample it was tuned against overstated quality, and the hold-out run
is what the number should be read as. Run-to-run variance is comparable to the size of the effect
a prompt change produces, which is why `backend/scripts/provider_eval.py` fixes the sample on disk
and `replay_extract.py` re-runs extraction against stored search text at zero search cost.

## Setup

### Prerequisites

- Python 3.11+
- Node.js 20+
- An API key for your chosen provider — [Perplexity](https://www.perplexity.ai/) (default)
  or [Groq](https://console.groq.com/) (free tier, set `PROVIDER=groq`) — needed only to
  actually run a scan; everything else works without one

### Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Create a `.env.local` file in the **repo root** (not `backend/`) with your Perplexity key:

```
# Required: choose one
PERPLEXITY_API_KEY=your-perplexity-key-here  # (default provider)
# GROQ_API_KEY=your-groq-key-here             # (optional, set PROVIDER=groq or
#                                             #  PROVIDER=groq+firecrawl to use)
# FIRECRAWL_API_KEY=your-firecrawl-key-here   # (optional, set PROVIDER=groq+firecrawl to use;
#                                             #  also needs GROQ_API_KEY)

# Optional: select which AI provider to use
# PROVIDER=perplexity      # default
# PROVIDER=groq            # requires GROQ_API_KEY
# PROVIDER=groq+firecrawl  # requires GROQ_API_KEY and FIRECRAWL_API_KEY; free-tier demo mode,
#                          # not sized for a full catalog scan
```

Run the API:

```bash
cd backend
set -a && source ../.env.local && set +a
.venv/bin/uvicorn app.main:app --port 8000
```

The API is now at `http://localhost:8000` (`/health` for a quick check).

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The Vite dev server proxies `/scans`, `/csv`, and `/health` to
the backend on port 8000 — start the backend first.

## Testing

```bash
# Backend
cd backend && .venv/bin/python -m pytest

# Frontend
cd frontend && npm test        # unit/component tests
cd frontend && npm run build   # typecheck + production build
cd frontend && npm run lint    # oxlint
```

Five backend tests are opt-in and skip by default (live Perplexity, Shopify, WooCommerce,
and Groq API calls, plus a real-catalog integration test) — they only run with specific env
vars set, so a normal `pytest` run stays free.

## Project status

Working end to end: CSV ingestion (plus a WooCommerce catalog source), column mapping with
auto-detection, scope selection with an up-front query-count and cost estimate, the async scan
job engine with live progress, price discovery across three provider configurations with a
SQLite cache, the margin engine, and the full report — verdict, scenario matrix, per-category
breakdown and product drill-down. Demo catalogs make all of it runnable without an API key.

Gated off: the Shopify catalog source, pending a cost-aware rewrite of its GraphQL query (which
exceeds Shopify's per-request cost cap). Not started: Allegro and open-web SERP as additional
price sources, deferred until real-world data justifies them; dedicated Shopify/WooCommerce apps.

Design documents and the implementation history for each phase are in `docs/superpowers/specs/`
and `docs/superpowers/plans/`.
