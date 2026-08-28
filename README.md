# IS_IT_WORTH_IT

A tool that answers one question for a dropshipping supplier's CSV catalog: **is it actually
worth it?** It takes a wholesale-price catalog, finds the cheapest real market offer for each
product (with a hard delivery-time filter — cheap offers shipping from the other side of the
world don't count), calculates margin against your own cost assumptions (commission, shipping,
VAT, returns), and produces a report: a verdict, a scenario matrix, and a per-product
drill-down.

V1 is a local, single-user web tool. The architecture is built to later grow into a
Shopify/WooCommerce app, but none of that integration work exists yet.

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
- **Price discovery** — Perplexity Sonar (structured output), with a SQLite cache keyed on
  `(ean, market, provider, max_delivery_days)` so you never pay twice for the same lookup.
- **Money** — always `Decimal`, never `float`, end to end.

## Setup

### Prerequisites

- Python 3.11+
- Node.js 20+
- A [Perplexity API key](https://www.perplexity.ai/) (needed only to actually run a scan —
  everything else works without one)

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
# GROQ_API_KEY=your-groq-key-here             # (optional, set PROVIDER=groq to use)

# Optional: select which AI provider to use
# PROVIDER=perplexity  # default
# PROVIDER=groq        # requires GROQ_API_KEY
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

Two backend tests are opt-in and skip by default (a live Perplexity call and a real-catalog
test) — they only run with specific env vars set, so a normal `pytest` run stays free.

## Project status

Phases 0 through 5c are complete: CSV ingestion, margin engine, Perplexity price provider with
caching, the async scan job engine, and the full wizard UI including the Report and
column-mapping screens described above. Not yet built: a Shopify/WooCommerce catalog source
(sketched, not implemented), and Allegro/open-web-SERP as additional price sources (deferred
until real-world data justifies them). See `docs/superpowers/specs/` and
`docs/superpowers/plans/` for the phase-by-phase design and implementation history.
