# Optional browser verification stage — design

## Context

This session's diagnosis found three distinct root causes for a bad extracted offer surviving into
a live eval run: a net-of-VAT price mistaken for gross (`net_price_flag`, `provider_eval.py`), a
cross-sell price bleeding from an unrelated product on the same page (`455461`, left on the backlog
by this same plan — see "Out of scope" below), and a stale search-index snippet describing a
listing that has since been discontinued or removed. The first two are at least partially
addressable at the text layer — a regex against the raw search snippet, a prompt instruction. The
third is not:

- The extraction prompt has nothing to work with — the cached snippet text that misled the model in
  the first place is the *only* input it ever sees, and that text was already stale when Firecrawl's
  index captured it.
- `backend/app/providers/liveness.py`'s bounded `HEAD` request cannot see it either: a discontinued
  listing overwhelmingly still returns `200 OK` — the store took the item off sale, it did not take
  the page down. `is_confirmed_dead()` only ever fires on a literal 404.
- A raw HTTP `GET` of the page body doesn't discriminate either. Measured this session: real
  e-commerce page bodies run 50 KB–1.8 MB, carrying embedded JSON blocks, price-history widgets and
  related-product sections, and a plain substring search for the extracted price against that raw
  HTML found the price "present" in **23 of 24** real URLs checked — regardless of whether the offer
  was actually good. A discontinued-listing page routinely still contains the old price somewhere in
  its markup (a cached fragment, a related-product card, a JSON-LD block that was never purged) even
  though nothing on the page a human would read says that price is buyable today. This was a real
  attempt at a pipeline-level HTTP-body check, and it was rejected on this evidence, not skipped.

The only thing that reliably sees a discontinued banner (e.g. "Produkt wycofany", "out of stock",
"nie znaleziono") is a real browser rendering the page — because many store frontends inject that
exact message via client-side JS/templating that a bare fetch never executes, and no cheap textual
comparison between "rendered text" and "template placeholder" replaces actually rendering it.
`backend/scripts/verify_offers_browser.mjs` (Task 1 of this plan, already restored and committed)
already does exactly this, as a standalone manual tool a human/agent runs after a live eval and
reads by hand. This document designs what an **optional, automated** version of that idea would
look like as a pipeline stage. It is a specification, not an implementation — no code in this
repository changes as a result of this document.

## Goal

**Definition of done for this document** (not for a future implementation): a reader who has never
seen this investigation can, from this spec alone, (a) understand exactly what class of defect the
stage catches that nothing else in this pipeline catches, (b) see the concrete cost of turning it
on, and (c) make the go/no-go call on building it — without needing to re-derive any of the
evidence above. This document is not asking the reader to agree to build the stage; it is handing
over the tradeoff, fully argued, for someone to decide.

## Where it would plug in

Two things are true today that shape this section, and both matter for a reader deciding whether
"plug in" is even the right verb yet:

1. **`price_flag`/`net_price_flag` exist only in `backend/scripts/provider_eval.py`'s `run_eval()`
   today** — they are eval-side enrichment computed after `provider.find_cheapest()` returns, never
   inside `app/providers/` itself. `base.py`'s `PriceProvider.find_cheapest()` returns a bare
   `OfferResult | None`; nothing in that return value or in `validate_offer_fields` carries either
   flag. So there is, right now, no live-scan code path that even knows an offer is "flagged" — only
   the offline eval tool does.
2. **The natural call-chain seam is the same one `FallbackProvider` (`app/providers/fallback.py`)
   already uses for its own secondary consultation**: `find_cheapest()` returns an `OfferResult`,
   the caller (today: `run_eval()`; in a hypothetical future: `run_scan()`/`orchestration.py`)
   already has both the `Product` and the `OfferResult` in hand at that point, which is exactly what
   `price_flag()`/`net_price_flag()` need as inputs. A browser-verification stage is a **third,
   optional consultation after the fact** — it does not sit inside `PriceProvider.find_cheapest()`,
   `_search()`, or `_extract()` at all, and it does not change `PriceProvider`'s Protocol. It is a
   post-processing step that takes `(product, offer, flag)` and returns a verdict, structurally
   parallel to how `price_flag`/`net_price_flag` are computed today — not a fourth thing bolted onto
   `FallbackProvider`'s two-provider composition.

Concretely, for `provider_eval.py` specifically: immediately after the existing
`net_flag = net_price_flag(...)` block (around line 463 of `provider_eval.py`) is exactly where a
call to this stage would go, gated behind the flag described below and only reached when `flag` or
`net_flag` is non-`None`.

For a live scan, the honest answer is that this stage has **no home to plug into yet**, because
`price_flag`/`net_price_flag` themselves haven't been ported from the eval tool into
`app/providers/` or `app/scans/`. Wiring this into a real scan is therefore two decisions, not one:
porting the flag computation into the live path (out of scope for this document and not decided
here), and then adding this stage after it. This document designs the stage on the assumption that
flagged offers exist somewhere to consume — it does not decide whether that place is
`provider_eval.py` alone (true today) or a future scan-time equivalent.

## Decisions

### Opt-in, off by default

The stage never runs unless explicitly requested. For `provider_eval.py`, that means a new CLI
flag, e.g. `--verify-flagged-browser`, defaulting to absent/`False`. With the flag unset,
`run_eval()`'s behavior is byte-for-byte what it is today — no new field appears in the output JSON,
no new dependency is imported, no new network call happens. A scan-level equivalent (a boolean field
on whatever scan-configuration object eventually carries provider selection) would follow the same
default: absent means "the pipeline behaves exactly as it does today." Off-by-default is not a
timid default here — it's the only default `liveness.py`'s own precedent supports: that check *is*
unconditional today, but it is a 5-second bounded `HEAD` request, three orders of magnitude cheaper
than a real headless-browser page load (see Cost, below). A precedent from a cheap, always-on check
does not transfer to an expensive one.

### Scoped to already-flagged offers, never to every found offer

The stage only ever runs on an offer that already carries `price_flag == "suspiciously_low"` or
`net_price_flag == "net_price"` (or a future flag of the same shape). It never runs on every `found`
offer.

Cost reasoning: in this session's own eval runs, `price_flag`-flagged entries were a small minority
of `found` offers (4 of 24 in one seed42 run, 6 of ~40 flagged entries total across both seeds
measured this session) — a real page load per offer is the kind of cost that is fine to pay for a
handful of suspicious entries and not fine to pay for every offer in a 17,500-product catalog scan.
Running it universally would mean adding a multi-second real-browser page load to every single
lookup in a scan — a cost multiplier on the *entire* scan, not a bounded addition to the small tail
that already looks wrong. Scoping to flagged offers keeps this stage's cost proportional to how
often the cheaper heuristics actually find something to be suspicious of, which is also exactly
the shape this project's own manual verification practice already uses: `price_flag` aims the
*human's* manual spot-check at the entries worth checking first, rather than a random sample. This
stage automates that same aiming, at the same scope.

### Reuses `verify_offers_browser.mjs`, does not duplicate it

This stage is a thin wrapper around the existing script, not a second Playwright integration. The
script's existing contract (see its own header comment) is:

```
node scripts/verify_offers_browser.mjs <found_offers.json> <out.json>
```

Input: a JSON array of `{sku, name, price, currency, seller, url}`. Output: the same records
enriched with `http_status`, `title`, `text` (full, untruncated rendered `document.body.innerText`),
`text_length`, and `likely_blocked`. The script already does the two things this stage would
otherwise have to reimplement: launching real headless Chrome (with an escape hatch for a system
Chrome binary via `CHROME_PATH`, and for an alternate Playwright install via `PLAYWRIGHT_MODULE`),
and rejecting (never accepting) cookie banners via `REJECT_SELECTORS`.

The interface this stage needs from it is exactly its existing CLI contract — an interface sketch,
not new code:

```
# Illustrative shape only — not a proposal to change the script's signature.
def verify_flagged_offers(flagged: list[FlaggedOffer]) -> list[VerificationRecord]:
    """
    1. Serialize `flagged` to the {sku, name, price, currency, seller, url}
       shape verify_offers_browser.mjs already expects.
    2. Invoke it as a subprocess (or spawn once and feed it a batch — the
       script already loops over its whole input array and writes
       incrementally after each URL, so a single subprocess call per batch
       is enough; there is no need to invoke it once per offer).
    3. Read back its output JSON and interpret it per the Asymmetric
       verdicts section below.
    """
```

This stage's own job is confined to steps 1 and 3: building the input list from already-flagged
offers, and turning the script's raw `{http_status, text, likely_blocked, error}` output into a
verdict. It does not touch the script's Playwright/cookie-handling internals at all — those stay
exactly as Task 1 restored them, and any future improvement to cookie-rejection selectors or
bot-detection heuristics benefits both this stage and the existing standalone manual usage for free.

### Asymmetric verdicts, matching `liveness.py`'s precedent

Three possible verdicts, not two: `confirmed_dead_or_changed`, `confirmed_ok`, and
`could_not_verify`. The critical asymmetry, copied directly from `liveness.py`'s own docstring
reasoning:

> Rejecting an offer needs certainty; "couldn't verify" must never be treated the same as
> "confirmed dead", or this would silently drop a large share of genuinely good offers from
> bot-gated marketplaces — worse than the dead-link problem it's meant to fix. See this project's
> own live audit: 7/7 real Allegro URLs 403'd a plain HTTP client even with a spoofed user agent.
> — `backend/app/providers/liveness.py`

The same reasoning applies here with, if anything, more force, because a real headless browser has
*more* ways to fail short of a clean answer than a bounded `HEAD` request does: a bot-check page
that a spoofed user agent doesn't clear, a `networkidle` timeout on a site with persistent
background polling, a cookie-banner variant `REJECT_SELECTORS` doesn't recognize and that blocks the
underlying content, a redirect loop, or the target site rate-limiting the scanning IP after a burst
of automated visits. Every one of these produces `likely_blocked: true`, a non-200 `http_status`
that isn't a clean 404, or a caught `error` in the script's output — and every one of those must map
to `could_not_verify`, never to `confirmed_dead_or_changed`. Concretely:

- `http_status == 404`, or the rendered `text` contains a store's own discontinued/not-found
  language (the exact phrases already catalogued from real audits: "Produkt wycofany", "nie
  została znaleziona", "SZUKANY PRODUKT NIE ZOSTAŁ ZNALEZIONY") → `confirmed_dead_or_changed`.
- A clean `200`, no blocking signal, and the claimed price (or a value within a small tolerance of
  it) is actually present in the rendered `text` → `confirmed_ok`.
- Anything else — `likely_blocked: true`, a script-level `error`, a non-404 non-200 status, a clean
  page whose rendered price doesn't match but that also doesn't carry any of the confirmed-dead
  language above — → `could_not_verify`. A `could_not_verify` verdict changes nothing about the
  offer: it is not persisted as a rejection, and it is not treated as a second confirmation either.
  It is exactly what its name says — the stage tried and could not get a certain answer — and the
  offer keeps whatever status it already had going in (still flagged, still un-rejected).

This three-way split, and specifically the refusal to let an inconclusive result collapse into
"bad," is the entire point of citing `liveness.py` here: it is the same asymmetry, reused for the
same reason, one layer further into the verification effort a flagged offer might get.

### Cost, stated plainly

This is explicitly **not** a small, bounded-cost addition in the way `liveness.py` is. Concretely:

- **New runtime dependency.** `verify_offers_browser.mjs` already requires `npm install playwright`
  and either `npx playwright install chromium` or a `CHROME_PATH` pointing at a system Chrome
  binary. Turning this stage on means anyone running a scan (or an eval) with it enabled needs that
  dependency present. Nothing in `backend/`'s current Python dependency set requires this — it is
  purely additive, and it is a different language/runtime (Node) from the rest of the provider
  pipeline.
- **Per-offer latency is seconds, not `liveness.py`'s bounded 5 seconds.** `liveness.py`'s
  `LIVENESS_TIMEOUT_SECONDS = 5.0` bounds a single `HEAD` request with no rendering. A real page
  load in `verify_offers_browser.mjs` waits for `networkidle` with a 25-second timeout, then an
  additional fixed 1-second settle, then a cookie-rejection attempt that itself budgets up to ~2
  seconds per selector tried — realistically several seconds per offer on a normal page, and up to
  the full 25-second timeout on a slow or bot-gated one. Multiplied across even a small number of
  flagged offers, this is not a rounding error on scan latency the way a 5-second-bounded `HEAD`
  request is.
- **This cost is why the scoping decision above matters as much as it does.** The combination of
  "scoped to a small flagged subset" and "still seconds per offer within that subset" is what makes
  this a defensible optional stage rather than an unconditional one. Removing the scoping decision
  and running this on every offer would multiply scan duration by a large, unbounded factor
  (bot-gated sites hitting the 25-second ceiling) for a catalog-sized run — nothing about this
  stage's design is meant to survive that removal.

### What it uniquely catches — and the negative evidence for why nothing cheaper does

Stated plainly, because this is the whole argument for building it at all: **the stale-snippet
class — a listing that was live when Firecrawl's index captured it and has since been discontinued,
pulled, or gone out of stock — is the only defect class in this investigation that nothing cheaper
already catches.** The other two classes diagnosed this session (net-of-VAT pricing, cross-sell
price bleed) are addressable, partially or fully, at the text/prompt layer without a browser at all
(`net_price_flag`'s regex-based approach is one such example, already shipped). This one is
structurally different, and the negative evidence already gathered says so directly:

- The extraction prompt sees only the cached snippet — there is nothing in that text for any prompt
  instruction to react to, because the staleness is a fact about the world *since* the snippet was
  captured, not a fact present anywhere in the snippet itself.
- `liveness.py`'s `HEAD` request confirms the URL still resolves — which it almost always still
  does for a discontinued listing, since stores remove products from sale far more often than they
  remove the page itself. A 200 tells you the door is still there; it says nothing about whether the
  shelf behind it is empty.
- A raw HTTP `GET` and a text search against the body was tried and rejected this session on direct
  evidence: the target price was found "present" in the raw HTML of **23 of 24** real URLs checked,
  independent of whether the offer was actually still good — meaning a check built this way would
  almost never disagree with the extraction, which makes it worthless as a discriminator.

A real browser is different only in that it executes the client-side rendering that produces the
actual discontinued/out-of-stock banner a human sees — the exact content a raw fetch or a HEAD
request structurally cannot obtain. That is the entire case for this stage's existence, and it is
also its complete boundary: it earns its cost only against this one class. Anyone reading this to
decide whether to build it should weigh that one, narrow, well-evidenced win against the cost
section above — not against the other two defect classes, which this stage was never meant to help
with and which stay solvable more cheaply elsewhere.

## Interface sketch (illustrative, not a build spec)

```
# Illustrative only — names, types and file location are all TBD at build
# time, not fixed by this document.

@dataclass(frozen=True)
class BrowserVerificationResult:
    verdict: Literal["confirmed_dead_or_changed", "confirmed_ok", "could_not_verify"]
    detail: str          # e.g. matched discontinued-language phrase, or "likely_blocked"
    http_status: int | None
    checked_at: datetime

def verify_flagged_offer(
    product: Product, offer: OfferResult, flag: str,
) -> BrowserVerificationResult:
    """Runs verify_offers_browser.mjs against offer.source_url and classifies
    its output per the asymmetric-verdict rules above. Never raises for a
    network/rendering failure — that maps to could_not_verify, mirroring
    liveness.is_confirmed_dead's own contract of returning a value rather
    than propagating an exception for an inconclusive network outcome.
    """
```

A caller (`run_eval()` today; a scan orchestrator in a hypothetical future) would call this only
when `price_flag` or `net_price_flag` is non-`None` on an entry, write `verdict`/`detail` alongside
the existing flag in the output record, and change nothing else about how that entry is scored or
reported — a `confirmed_dead_or_changed` verdict is a strong signal for a human reviewing the eval
output to reject the entry, not an automatic rejection this document is proposing to wire in as
pipeline logic.

## Non-goals (explicit)

- No code in this repository changes as a result of this document. `verify_offers_browser.mjs`,
  `backend/app/providers/`, and `provider_eval.py` are all untouched by this task.
- No decision is made here about porting `price_flag`/`net_price_flag` into the live scan path —
  that is a separate, undecided piece of work this document explicitly does not resolve (see
  "Where it would plug in").
- No decision is made here about whether to actually build this stage. That is the go/no-go call
  this document exists to inform, not to make.
- No handling of the cross-sell price-bleed class (`455461`) is proposed here — per this plan's own
  scope, that stays a backlog item with its root cause written down, not a browser-verification
  problem (a page rendering correctly does not help distinguish which price on it belongs to which
  product; that is an extraction-attribution problem, not a rendering problem).

## Out of scope

Everything this plan already put on the backlog stays there. Specifically, the cross-sell bleed
(`455461`) gets no prompt change here or anywhere in this document — the extraction prompt already
carries roughly 700 tokens of instruction, this repo has repeatedly measured prompt length as the
dominant per-call cost against a hard daily token ceiling, and it has repeatedly measured added
prose as unreliable against exactly this bug class. It stays on the backlog with its root cause now
written down, unrelated to whatever the reader decides about this document's stage.
