"""Persistent replay harness: re-runs ONLY the extraction step of
`FirecrawlProvider` against search snippets already saved by a prior
`provider_eval.py --keep-raw` run, at zero search-step cost (no Firecrawl
credits, no Groq compound/search-orchestration tokens).

Why this exists: 2026-09-02's price-bleed bugfix session (see
`.claude/rules/groq-compound-free-tier-reliability.md`, "Aktualizacja
2026-09-02 (piąta)") discovered a fourth, independent Groq rate limit — a
200,000 tokens/day budget on the extraction model itself
(`openai/gpt-oss-20b`), shared by BOTH `GroqProvider._extract` and
`FirecrawlProvider._extract`. That session replayed stored `search_raw_text`
through `FirecrawlProvider._extract` directly (skipping `_search` entirely)
to test a prompt fix without spending any more of that scarce budget — using
a one-off script that lived in `/tmp` and was lost when the session ended
(see `.claude/rules/subagent-research-koszt-i-przetrwanie.md`'s "write to
disk, not just to memory" principle — applied here at the level of the
*tool itself*, not just its findings). This script makes that technique
permanent, tracked, and resumable.

It reuses `FirecrawlProvider._extract` completely unmodified — same prompt
builder, same JSON-schema response parsing, same `call_with_retry` — so
there is no hand-rolled copy of the extraction logic that could silently
diverge from production. On a `ProviderRateLimited` (raised by
`call_with_retry` after exhausting its own internal retries — see
`app/providers/retry.py`), this script reads the parsed `.retry_after`
seconds straight off the exception and sleeps that long (capped by
`--wait-cap-seconds`) before retrying the SAME entry, up to a total
`--budget-hours` wall-clock ceiling for the whole invocation.

Progress is written to `--out` after EVERY entry, not batched, so an
invocation killed mid-run (session limit, Ctrl-C, crash) loses at most the
one entry it was working on — the next invocation resumes automatically,
skipping every SKU already present in the output file.

Usage (from `backend/`, after sourcing ../.env.local per README.md):

    set -a && source ../.env.local && set +a
    .venv/bin/python scripts/replay_extract.py \\
        --source scripts/eval_results/groq+firecrawl_seed42_n25_1788352269.json

    # Targeted spot-check of two SKUs, launched detached from the session:
    nohup .venv/bin/python scripts/replay_extract.py \\
        --source scripts/eval_results/groq+firecrawl_seed42_n25_1788352269.json \\
        --skus MQKJ3ZM/A,BD620678 > replay.log 2>&1 &
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.providers.base import ProviderAuthError, ProviderRateLimited  # noqa: E402
from app.providers.firecrawl import FirecrawlProvider  # noqa: E402

SCRIPT_DIR = Path(__file__).resolve().parent
RESULTS_DIR = SCRIPT_DIR / "eval_results"

# Fallback sleep when a ProviderRateLimited carries no parsed retry_after
# (the body didn't match retry.py's "try again in ..." pattern) — matches
# groq_quota.py's spirit of a conservative default rather than a tight
# guess. Real observed waits for the gpt-oss-20b TPD wall are ~18-45
# minutes (see the rule file cited above), so 60s is deliberately just a
# "don't hammer the API in a tight loop" floor, not a real estimate.
DEFAULT_RATE_LIMIT_WAIT_SECONDS = 60.0

# Matches a block boundary line emitted by
# FirecrawlProvider._format_snippets: "{index}. {title}" at the START of a
# line. Only a match whose captured number continues the 1, 2, 3, ...
# sequence is accepted as a real boundary — see _find_block_boundaries.
_BOUNDARY_RE = re.compile(r"^(\d+)\. ")


def _find_block_boundaries(lines: list[str]) -> list[int]:
    """Returns the line indices that start a snippet block, in order.

    A candidate "N. " line is only accepted when N equals the next expected
    integer in a strictly increasing sequence starting at 1 — this guards
    against a stray "N. "-shaped line inside a multi-line description (e.g.
    a scraped product ID like "2. Some heading") being mistaken for a real
    entry boundary.

    Important limitation, worth knowing before trusting parse_and_validate's
    round-trip check as a complete guarantee: when a candidate line IS
    rejected here, its text is simply absorbed as description content of
    whatever block it falls inside — and the resulting (title, description,
    url) split still reconstructs byte-for-byte via _format_snippets,
    because the split/join is a pure, fully invertible function of the
    accepted boundaries alone. So the round-trip check only catches a
    genuine STRUCTURAL deviation from _format_snippets's exact output shape
    (a block with fewer than 3 lines, a url line missing its expected
    3-space indent, wrong starting number, etc.) — it provides no defense
    against a coincidentally-sequential "N. " line silently merging two
    real entries into one (wrong grouping, but still self-consistent text).
    Validated live 2026-09-02 against 21/21 real `found`-outcome entries
    with no such collision; treat that as "empirically rare on real
    Firecrawl snippets", not as a structural guarantee.
    """
    boundaries = []
    expected = 1
    for i, line in enumerate(lines):
        match = _BOUNDARY_RE.match(line)
        if match and int(match.group(1)) == expected:
            boundaries.append(i)
            expected += 1
    return boundaries


def parse_snippets(text: str) -> list[dict]:
    """Reverses FirecrawlProvider._format_snippets. Raises ValueError on any
    structural problem (e.g. a block with fewer than the 3 lines a
    title/description/url block must have). Callers MUST NOT trust this
    result without the round-trip check in parse_and_validate — a
    misdetected boundary can produce a result that parses without raising
    yet does not represent the original text at all.
    """
    if text == "":
        return []
    lines = text.split("\n")
    boundaries = _find_block_boundaries(lines)
    if not boundaries:
        raise ValueError("no numbered entry boundaries found in search_raw_text")

    results = []
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(lines)
        block = lines[start:end]
        if len(block) < 3:
            raise ValueError(
                f"block starting at line {start} has only {len(block)} line(s); "
                "a title/description/url block needs at least 3"
            )

        title_match = _BOUNDARY_RE.match(block[0])
        assert title_match is not None  # guaranteed by _find_block_boundaries
        title = block[0][title_match.end():]

        url_line = block[-1]
        url = url_line[3:] if url_line.startswith("   ") else url_line

        desc_lines = list(block[1:-1])
        if desc_lines:
            first = desc_lines[0]
            desc_lines[0] = first[3:] if first.startswith("   ") else first
            description = "\n".join(desc_lines)
        else:
            description = ""

        results.append({"title": title, "description": description, "url": url})
    return results


def parse_and_validate(text: str) -> list[dict] | None:
    """Parses `text` and returns the result ONLY if re-rendering it through
    FirecrawlProvider._format_snippets reproduces `text` byte-for-byte.
    Returns None (never raises) when parsing fails outright or the
    round-trip doesn't match — both are the same "unparseable" outcome to
    every caller of this function.
    """
    try:
        parsed = parse_snippets(text)
    except ValueError:
        return None
    if FirecrawlProvider._format_snippets(parsed) != text:
        return None
    return parsed


def classify(entry: dict, offer) -> tuple[str, dict]:
    """Compares a freshly-replayed offer against the source entry's
    recorded outcome. `offer` is an OfferResult or None, as returned by
    FirecrawlProvider._extract.
    """
    record: dict = {
        "new_price": str(offer.price) if offer is not None else None,
        "new_source_url": offer.source_url if offer is not None else None,
    }

    if entry.get("outcome") == "found":
        old_price_raw = (entry.get("offer") or {}).get("price")
        record["old_price"] = old_price_raw
        try:
            old_price = Decimal(str(old_price_raw))
        except (InvalidOperation, TypeError):
            old_price = None

        if offer is None:
            status = "regression_now_not_found"
        elif old_price is not None and Decimal(str(offer.price)) == old_price:
            status = "match"
        else:
            status = "PRICE_CHANGED"
    else:
        # outcome was "not_found" or "error" but search_raw_text still
        # exists — there is no recorded price to compare against, so this
        # replay is purely informational (see module docstring: a general
        # tool, not one hardcoded to the found-only regression-sweep case).
        record["old_price"] = None
        status = "replayed_no_baseline"

    record["status"] = status
    return status, record


def _budget_exhausted(start_time: float, budget_hours: float) -> bool:
    return (time.monotonic() - start_time) >= budget_hours * 3600


def _replay_with_retry(
    provider: FirecrawlProvider,
    parsed_results: list[dict],
    market: str,
    max_delivery_days: int,
    wait_cap_seconds: float,
    start_time: float,
    budget_hours: float,
    sku: str,
):
    """Calls provider._extract, retrying the SAME entry on ProviderRateLimited
    until it succeeds, a different exception occurs (propagated to the
    caller), or the wall-clock budget runs out. Returns (offer, timed_out) —
    timed_out=True means the caller should stop the whole run, not just this
    entry, leaving it unresolved for the next invocation to pick up.
    """
    while True:
        if _budget_exhausted(start_time, budget_hours):
            return None, True
        try:
            offer = provider._extract(parsed_results, market, max_delivery_days)
            return offer, False
        except ProviderRateLimited as exc:
            wait = exc.retry_after if exc.retry_after is not None else DEFAULT_RATE_LIMIT_WAIT_SECONDS
            wait = min(wait, wait_cap_seconds)
            print(
                f"  {sku}: rate-limited (parsed retry_after={exc.retry_after}), "
                f"sleeping {wait:.0f}s before retrying this entry"
            )
            time.sleep(wait)


def build_provider(groq_api_key: str) -> FirecrawlProvider:
    """Separated out from main() so tests can monkeypatch this to return a
    FirecrawlProvider wired to a fake HTTP client — same seam pattern as
    provider_eval.py's build_provider. api_key="unused": this harness never
    calls FirecrawlProvider._search (the Firecrawl API), only ._extract
    (Groq's extraction model) — see the controller ruling in the task brief
    for why this reuses the real provider unmodified rather than a
    hand-rolled HTTP call.
    """
    return FirecrawlProvider(api_key="unused", groq_api_key=groq_api_key)


def _write_output(out_path: Path, source_path: Path, checked: dict) -> None:
    """Writes the checkpoint atomically: the whole point of writing after
    every entry is surviving a mid-run kill (session limit, Ctrl-C, crash —
    see .claude/rules/sdd-interrupted-by-account-limit.md), and a plain
    write_text() can itself be killed mid-write, leaving truncated/corrupt
    JSON that then crashes the NEXT invocation's resume-read. Writing to a
    sibling temp file and os.replace()-ing it into place is atomic on
    POSIX (same filesystem, same directory) — out_path either has the old
    complete content or the new complete content, never a partial write.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"source": str(source_path), "checked": checked}, indent=2)
    tmp_path = out_path.with_name(f".{out_path.name}.tmp{os.getpid()}")
    tmp_path.write_text(payload)
    os.replace(tmp_path, out_path)


def run_replay(
    provider: FirecrawlProvider,
    source_results: list[dict],
    checked: dict[str, dict],
    *,
    market: str,
    max_delivery_days: int,
    wait_cap_seconds: float,
    budget_hours: float,
    sku_filter: set[str] | None,
    limit: int | None,
    out_path: Path,
    source_path: Path,
    start_time: float | None = None,
) -> dict[str, int]:
    """Drives the replay over `source_results`, mutating `checked` in place
    and writing it to `out_path` after every resolved entry. Returns
    per-status counts for entries resolved during THIS call only (entries
    already in `checked` on entry are skipped and not counted).

    Split out from main() so tests can drive it directly against a
    FirecrawlProvider wired to a fake HTTP client, same pattern as
    provider_eval.py's run_eval/main split.
    """
    if start_time is None:
        start_time = time.monotonic()

    status_counts: dict[str, int] = {}
    processed = 0

    for entry in source_results:
        sku = entry.get("sku")
        if not sku or sku in checked:
            continue
        if sku_filter is not None and sku not in sku_filter:
            continue
        raw_text = entry.get("search_raw_text")
        if raw_text is None:
            continue
        if limit is not None and processed >= limit:
            break

        if _budget_exhausted(start_time, budget_hours):
            print("budget exhausted, stopping before this entry")
            break

        parsed = parse_and_validate(raw_text)
        if parsed is None:
            checked[sku] = {"status": "parse_failed"}
            _write_output(out_path, source_path, checked)
            status_counts["parse_failed"] = status_counts.get("parse_failed", 0) + 1
            processed += 1
            print(f"{sku}: parse_failed")
            continue

        try:
            offer, timed_out = _replay_with_retry(
                provider, parsed, market, max_delivery_days,
                wait_cap_seconds, start_time, budget_hours, sku,
            )
        except ProviderAuthError:
            # Not an ordinary per-entry failure: a rejected key fails
            # identically for every remaining entry (see base.py's own
            # docstring), so recording one "error" per SKU and moving on
            # would burn the rest of this invocation's budget proving only
            # that the key is still bad. Same handling as provider_eval.py's
            # run_eval. The entry stays unresolved for the next invocation.
            print(f"{sku}: AUTH ERROR — aborting run")
            raise
        except Exception as exc:  # noqa: BLE001 — classify every OTHER failure, don't crash the batch
            checked[sku] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            _write_output(out_path, source_path, checked)
            status_counts["error"] = status_counts.get("error", 0) + 1
            processed += 1
            print(f"{sku}: error ({type(exc).__name__}: {exc})")
            continue

        if timed_out:
            print(f"budget exhausted mid-retry on {sku}, stopping (entry left unresolved)")
            break

        status, record = classify(entry, offer)
        checked[sku] = record
        _write_output(out_path, source_path, checked)
        status_counts[status] = status_counts.get(status, 0) + 1
        processed += 1
        print(f"{sku}: {status}  old={record.get('old_price')}  new={record.get('new_price')}")

    return status_counts


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True,
                         help="path to an eval_results/*.json file (provider_eval.py --keep-raw output)")
    parser.add_argument("--out", type=Path, default=None,
                         help="default: scripts/eval_results/replay_<source-stem>.json")
    parser.add_argument("--market", default="PL")
    parser.add_argument("--max-delivery-days", type=int, default=5)
    parser.add_argument("--wait-cap-seconds", type=float, default=1500.0,
                         help="per-attempt sleep cap, 25 min (matches the plan's stated per-attempt cap)")
    parser.add_argument("--budget-hours", type=float, default=6.0,
                         help="total wall-clock time this invocation will spend before stopping cleanly")
    parser.add_argument("--skus", default=None,
                         help="comma-separated SKU allowlist; omit to replay every eligible entry")
    parser.add_argument("--limit", type=int, default=None,
                         help="process at most this many NEW entries this invocation")
    args = parser.parse_args(argv)

    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key:
        raise SystemExit("GROQ_API_KEY is not set in the environment")

    out_path = args.out or RESULTS_DIR / f"replay_{args.source.stem}.json"
    sku_filter = {s.strip() for s in args.skus.split(",")} if args.skus else None

    data = json.loads(args.source.read_text())
    source_results = data.get("results", [])

    checked: dict[str, dict] = {}
    if out_path.exists():
        # The atomic write in _write_output means a file at rest here should
        # never be truncated/corrupt from OUR OWN writes — but defend
        # against corruption from some other cause (a manual edit, a copy
        # interrupted by something outside this script) rather than crash
        # the whole invocation on a resume. Treat an unreadable file the
        # same as "no prior file": start fresh rather than lose the run.
        try:
            checked = json.loads(out_path.read_text()).get("checked", {})
        except (json.JSONDecodeError, OSError) as exc:
            print(f"WARNING: {out_path} exists but is not valid JSON ({exc}); "
                  f"starting this invocation with no prior progress")

    eligible = [
        e for e in source_results
        if e.get("sku") and e.get("search_raw_text") is not None
        and (sku_filter is None or e["sku"] in sku_filter)
    ]
    already_resolved = sum(1 for e in eligible if e["sku"] in checked)
    to_process = len(eligible) - already_resolved
    print(f"{len(eligible)} eligible entries, {already_resolved} already resolved, "
          f"{to_process} to process this invocation" + (
              f" (limit {args.limit})" if args.limit is not None else ""
          ))

    provider = build_provider(groq_api_key)

    status_counts = run_replay(
        provider, source_results, checked,
        market=args.market, max_delivery_days=args.max_delivery_days,
        wait_cap_seconds=args.wait_cap_seconds, budget_hours=args.budget_hours,
        sku_filter=sku_filter, limit=args.limit,
        out_path=out_path, source_path=args.source,
    )

    processed = sum(status_counts.values())
    print(f"\n{processed}/{to_process} entries resolved this invocation")
    for status in sorted(status_counts):
        print(f"  {status}: {status_counts[status]}")
    print(f"Output written to {out_path}")


if __name__ == "__main__":
    main()
