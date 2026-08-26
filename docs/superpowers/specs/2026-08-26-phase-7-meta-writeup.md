# Phase 7 — Meta: reguły, skille, subagenty (spisanie)

Master plan: `2026-07-28-is-it-worth-it-design.md`, lines 137-169. That section asked for the
meta-layer to be **designed before any code**. In practice it grew organically, from real friction
across Phases 1-6, and diverged from the upfront list in both directions — some planned items were
never needed, some unplanned items turned out to be the most valuable mechanism in the project. This
document is the "spisanie": what was planned, what exists, and where each guarantee actually lives.

## Housekeeping fixed by this phase

`.claude/rules/`, `.claude/hooks/`, and `.claude/agent-memory/repo-reviewer/` (620 lines of
accumulated review knowledge), plus the current `CLAUDE.md` and `.claude/settings.json` (hook
wiring), had **never been committed to git** — present only in the working tree since the initial
commit, across all of Phases 1-6. Fixed in commit `2ff915c`. Nothing about their *content* changed;
they were simply exposed to the same loss risk as any other uncommitted file (`git clean`, a wiped
machine, a bad `checkout`) despite being exactly the kind of durable, cross-session knowledge
`~/.claude/rules/project-learning-loop.md` exists to protect.

## Rules (`.claude/rules/`)

| Planned | Status | Where it actually lives |
|---|---|---|
| `money.md` | **Exists**, but not what was planned | Not "Decimal, explicit currencies, rounding rules" as prose — that guarantee is enforced by the type system instead (`OfferResult.price: Decimal`, `currency: str` in `backend/app/providers/base.py`). The actual `money.md` holds five sharper lessons pulled from one real 115k-row file: `csv.Sniffer` corrupting `doublequote`, non-deterministic `set` iteration for column-alias resolution, `"0.00"` as a price-absence marker, spec sizing being illustrative only, and real-data testing needing to happen early. All five passed the synthetic test suite first. |
| `provider-contract.md` | **Never written as a file** | The contract lives as code: the `PriceProvider` Protocol plus the `ProviderUnavailable` vs. `None` distinction, both documented in docstrings in `backend/app/providers/base.py`. A prose rule would just restate the type signature — the Protocol is the contract and mypy/the tests enforce it, which a `.md` file cannot. |
| `no-hallucinated-prices.md` | **Never written as a file** | The policy is `backend/app/providers/anomaly.py`'s `detect_anomaly()`: `LOW_CONFIDENCE_THRESHOLD`, `BELOW_WHOLESALE`, `UNUSUALLY_HIGH`. The verification checklist's "every price has a clickable source; sourceless offers are excluded" is threaded structurally — `OfferResult.citations`/`source_url` flow through `reports/api.py` and are persisted in `scans/store.py` — not asserted as a rule an agent could ignore. |
| *(not planned)* `frontend-ui.md` | **Exists** | Added after the bare `data-*:` Tailwind-variant bug was found independently 5 times across 3 phases — the upfront plan had no way to anticipate a frontend-specific rule because Phase 1-4 was backend-only. Now mechanically enforced by `.claude/hooks/shadcn-guard.sh`, not just documented. |
| *(not planned)* `planning.md` | **Exists** | Added after Phase 5c's plan-conformance trap (7 clean task reviews, 1 shipped bug) — a process lesson about *how this repo reviews*, not about any code path, so it couldn't have been anticipated by a pre-code design pass either. |

Takeaway: the two rules that stayed unplanned-for (`money.md`'s actual content, `provider-contract.md`,
`no-hallucinated-prices.md`) all became either code-enforced guarantees or sharper real-data lessons
than the abstract categories the plan named. The two rules the plan couldn't have predicted
(`frontend-ui.md`, `planning.md`) turned out to matter more than any of the three it did predict —
consistent with this project's own recurring finding that guarantees discovered by contact with real
data/second implementations beat guarantees designed in advance.

## Skills (`.claude/skills/`)

| Planned | Status | Assessment |
|---|---|---|
| `add-price-provider` | **Not written** | Only one provider (Perplexity) has ever been built. A "step by step" skill generalized from a single example is a guess, not a distillation — this project's own `source-protocol-invariants.md` memory is direct evidence of what happens when a second implementation reveals a contract the first one never wrote down. Recommendation: write this skill from the diff *when/if* a second price provider is actually added, not before. |
| `add-catalog-source` | **Not written, but now earned** | Two implementations exist (`CsvCatalogSource`, `ShopifyCatalogSource`), and the second one silently violated three guarantees the first enforced (EAN dedup, UPC-A padding, blank-name skip) — caught only by whole-branch review, documented in `source-protocol-invariants.md` and flagged in `2026-08-26-shopify-source-sketch-design.md` as a named follow-up before a third source (WooCommerce). This is exactly `project-learning-loop.md`'s "a procedure reproduced a second time → a skill" trigger. **Concrete next step**, not just a recommendation: extract the shared normalization layer (dedup/padding/blank-skip) *and* write this skill together, before WooCommerce, so the skill documents a contract that's actually enforced by shared code rather than prose a third implementation could ignore the same way the second one did. |
| `cost-safety` | **Not written** | Covered by `backend/tests/cache/test_sqlite_cache.py` and the provider test suite (`backend/tests/providers/`, including a `test_perplexity_live.py` gated the same way the Shopify live test is) rather than a documented procedure. The verification checklist's cache-driven "~0 new queries on rescan" item is tested, not just asserted. No gap here worth closing speculatively — revisit only if a second LLM-backed provider is added and the mocking approach needs to be taught rather than copied. |

## Subagents (`.claude/agents/`)

| Planned | Status |
|---|---|
| `report-analyst` | **Never created.** No recurring problem in report/aggregation logic ever needed a dedicated design-and-verify subagent; general whole-branch review covered it. Not recommended retroactively absent a concrete recurring failure in that logic. |
| *(not planned)* `repo-reviewer` | **The single most load-bearing mechanism in the project**, and entirely unplanned. Per this repo's own `CLAUDE.md`: "every bug that mattered here was caught by a whole-branch review and none by `npm test`, `npm run build` or `npm run lint`." Lives at `~/.claude/agents/repo-reviewer.md` (machine-wide, not this project's `.claude/agents/` — this project has no `.claude/agents/` directory at all), with per-repo memory at `.claude/agent-memory/repo-reviewer/` now committed per the housekeeping fix above. |

## Net assessment

The pre-code "design the meta-layer first" instruction in this project's original `CLAUDE.md`
bootstrap step turned out to be the wrong sequencing for this project: 3 of 6 planned rules were
never needed as written, all 3 planned skills were premature (0 or 1 real instances to generalize
from at design time), and the one subagent that actually mattered was never in the plan at all. What
did work, every time, was writing the rule/skill *after* a bug or friction point repeated — which is
also this repo's own stated model (`project-learning-loop.md`, `planning.md`'s stale-when clauses).
`add-catalog-source` is the one item on the original list that has now crossed that threshold and is
worth building for real.

## Open, concrete follow-ups

1. **Shared `CatalogSource` normalization layer + `add-catalog-source` skill** — build together,
   before WooCommerce. Source: `source-protocol-invariants.md` + the Shopify design spec's follow-up
   note.
2. **Manual Shopify dev store setup**, still not done, still human-only (Partners account, dev
   store, custom app credentials) — no such account exists in this environment. Steps are in
   `2026-08-26-shopify-source-sketch-design.md`'s "Setup required before the live test can run"
   section.
