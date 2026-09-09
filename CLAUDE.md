# IS_IT_WORTH_IT — working notes

Conventions and traps that the code does not explain on its own. Read this before changing
anything in `backend/app` or `frontend/src`.

## Definition of done

A change is done when all four of these pass — not three:

```bash
cd backend  && .venv/bin/python -m pytest
cd frontend && npm test && npm run build && npm run lint
```

`npm run build` is the typecheck (`tsc -b`), so it is not optional. Five backend tests are
opt-in and skip unless their env vars are set (live Perplexity / Groq / Shopify / WooCommerce
calls and a real-catalog integration test); a plain `pytest` run never spends money.

## Conventions

- **Money is `Decimal`, never `float`, end to end** — parsing, margin math, serialization. A
  `float` anywhere in a price path is a bug even when the test passes.
- **API-first.** All domain logic (CSV parsing, EAN validation, price lookup, margin math)
  lives in `backend/app`. The frontend is a thin client: no domain logic, no router, no
  data-fetching library.
- **Provider keys live in `.env.local` at the repo root**, not in `backend/`. The backend is
  started with `set -a && source ../.env.local && set +a`.
- **Comments carry the measurement, not a pointer to it.** When a constant was chosen from a
  live run, restate the observed numbers in the comment so the choice can be re-derived from
  the file alone.

## Traps — looks standard, behaves differently

- **Never `csv.Sniffer`.** It cannot be trusted to detect `doublequote` and silently corrupts
  rows on real supplier files. Every reader passes an explicit dialect.
- **`"0.00"` (and Polish comma-decimal `"0,00"`) is a price-on-request marker, not a price.**
  Those rows are dropped, not treated as free products. One real 115k-row supplier file had
  ~37k of them.
- **Groq's binding free-tier limit is not the documented 250 requests/day.** It is an
  undocumented tokens-per-day budget on an internal orchestration model, which no response
  header exposes — `x-ratelimit-remaining-tokens` reports a different model's counter and can
  look healthy on an already-dead day. `backend/scripts/groq_quota.py` probes for this.
- **`FallbackProvider`'s primary/secondary are not quota-independent.** `FirecrawlProvider._extract`
  calls the same Groq extraction model `GroqProvider._extract` does; only the *search* step is
  genuinely separate.
- **`FallbackProvider`'s rate-limit latch is per-instance and permanent for the run.** The
  provider is a process-wide singleton, so `run_scan()` must call `reset()` at the start of
  every scan.
- **The Shopify catalog source is deliberately gated off** in `backend/app/scans/api.py`. Its
  GraphQL query exceeds Shopify's per-query cost cap and it has no pagination cap or
  response-shape error handling. Do not un-gate it without both.

## Evaluating provider changes

Prompt tuning measured only on the sample it was tuned against overstates quality — measured
here at 84% on the tuning sample versus 64% on a fresh hold-out. Run-to-run variance is
comparable to the size of the effect a prompt change produces, so:

- `backend/scripts/provider_eval.py` — fixed, seeded, on-disk samples so runs are comparable.
- `backend/scripts/replay_extract.py` — replays stored search text through extraction only, at
  zero search-step cost, and checkpoints atomically after every entry so a mid-run kill resumes.
- `backend/scripts/build_extraction_gold.py` — builds the gold set the replays are scored against.
- `backend/scripts/verify_offers_browser.mjs` — opens every `found` offer's `source_url` in a real
  browser (bare HTTP clients get 403'd by Allegro and other bot-gated stores) and dumps the
  rendered page text, so a human/agent can judge product match, price match, and whether a lower
  price is visible elsewhere on the same page. Needs Playwright and a Chrome binary, pointed at via
  two optional env vars: `PLAYWRIGHT_MODULE` (module/path to import `chromium` from, defaults to
  the plain `playwright` package) and `CHROME_PATH` (defaults to Playwright's bundled Chromium
  when unset). Run from `backend/`:
  `PLAYWRIGHT_MODULE=... CHROME_PATH=... node scripts/verify_offers_browser.mjs <found_offers.json> <out.json>`.

Always report the hold-out number, not the tuning number.
