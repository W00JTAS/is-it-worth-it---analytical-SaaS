"""Builds a curated, stable gold-set fixture for `replay_extract.py` out of
two prior `provider_eval.py --keep-raw` result files.

Why this exists: every prompt-tuning measurement in this project so far
compared runs against a MOVING target — a fresh sample (or a fresh seed) each
time, with real-world listing changes and Groq's own variance layered on top
of whatever the prompt change actually did. Run-to-run variance turned out
comparable to the size of the effect being measured: the hold-out (seed=7) run
and the tuning sample (seed=42)
disagreed by 20 points, and three of five "not_found" entries flipped to
"found" on a mere re-run of the identical prompt.

This script fixes that by freezing a fixed set of (search_raw_text, confirmed
price) pairs on disk. `search_raw_text` is captured by `provider_eval.py`
(scripts/provider_eval.py:345-351 as of 2026-09-02) but nothing downstream
ever reads it back — it is write-only until `replay_extract.py` (Task 2 of
this plan) added a consumer. A gold set is that consumer's fixed input: every
future prompt change gets replayed against these exact same snippets, so a
before/after comparison measures the prompt, not the sampling.

Source selection is deliberately a fixed, hardcoded pair of files, not a glob
over `eval_results/*.json` — that directory accumulates exploratory runs
(failed experiments, DNS-outage-contaminated partial runs, pre-manual-
correction snapshots) that must NOT silently enter the gold set just by
existing on disk. Widening the source set is a deliberate editorial decision,
made by editing DEFAULT_SOURCES below, not something this script infers.

An entry is kept only if:
  - `outcome == "found"` (no recorded price to gold-set otherwise),
  - `search_raw_text` is present and non-empty (nothing for
    `replay_extract.py` to replay otherwise),
  - the offer does NOT carry `price_flag == "suspiciously_low"` — that flag
    has a 6/6 hit rate against manual verification in this project's history
    (see the rule file above), so an entry still carrying it has not been
    confirmed and does not belong in a fixture whose whole point is a
    confirmed price. Both files this script currently reads have that flag
    already cleared to null for every found entry (the manual correction
    already happened out-of-band when those files were produced) — the check
    is here so a future re-run against fresher, not-yet-corrected source
    files can't slip an unverified price into the gold set.

Usage (from `backend/`):

    .venv/bin/python scripts/build_extraction_gold.py
    .venv/bin/python -m pytest tests/scripts/test_build_extraction_gold.py

Idempotent by construction: given the same source files, running this twice
produces byte-identical output (no wall-clock timestamp is embedded — the
`summary` block names the source files it was built from instead, which is
the only thing that actually changes if the fixture is regenerated later
against a different source pair).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SCRIPT_DIR = Path(__file__).resolve().parent
RESULTS_DIR = SCRIPT_DIR / "eval_results"
BACKEND_DIR = SCRIPT_DIR.parent

DEFAULT_SOURCES = [
    RESULTS_DIR / "groq+firecrawl_seed42_n25_1788352269.json",
    RESULTS_DIR / "groq+firecrawl_seed7_n25_1788358094.json",
]
DEFAULT_OUT = BACKEND_DIR / "tests" / "fixtures" / "extraction_gold.json"


def is_gold_candidate(entry: dict) -> bool:
    """True iff `entry` (one item of a provider_eval.py results list) has a
    confirmed price and a replayable snippet — see the module docstring for
    exactly what each of the three conditions guards against.
    """
    if entry.get("outcome") != "found":
        return False
    if not entry.get("search_raw_text"):
        return False
    offer = entry.get("offer") or {}
    if offer.get("price_flag") == "suspiciously_low":
        return False
    return True


def load_results(path: Path) -> list[dict]:
    """Reads one provider_eval.py --keep-raw output file's `results` list."""
    data = json.loads(path.read_text())
    return data.get("results", [])


def build_gold_entries(source_paths: list[Path]) -> tuple[list[dict], dict[str, int]]:
    """Reads every file in `source_paths` and keeps only entries that pass
    `is_gold_candidate`. Returns (merged kept entries, kept-count per source
    file name) — the counts are for the CLI's one-line summary, not stored in
    the merged entries themselves.
    """
    kept: list[dict] = []
    counts_by_source: dict[str, int] = {}
    for path in source_paths:
        source_kept = [e for e in load_results(path) if is_gold_candidate(e)]
        counts_by_source[path.name] = len(source_kept)
        kept.extend(source_kept)
    return kept, counts_by_source


def build_gold_payload(source_paths: list[Path]) -> dict:
    """Builds the full `{"summary": ..., "results": [...]}` fixture payload,
    in the exact shape `replay_extract.py --source <this file>` already
    knows how to read unmodified.
    """
    kept, counts_by_source = build_gold_entries(source_paths)
    summary = {
        "description": (
            "Curated gold-set fixture: found-outcome entries with a "
            "manually-confirmed, non-suspicious price, merged from the "
            "source files below. Regenerate with "
            "`scripts/build_extraction_gold.py`; do not hand-edit."
        ),
        "source_files": [path.name for path in source_paths],
        "counts_by_source": counts_by_source,
        "total": len(kept),
    }
    return {"summary": summary, "results": kept}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sources", type=Path, nargs="+", default=DEFAULT_SOURCES,
                         help="eval_results/*.json files to merge (default: the two fixed source files)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                         help=f"fixture output path (default: {DEFAULT_OUT})")
    args = parser.parse_args(argv)

    payload = build_gold_payload(args.sources)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")

    counts = payload["summary"]["counts_by_source"]
    breakdown = " + ".join(f"{counts[name]} from {name}" for name in counts)
    print(f"kept {breakdown} = {payload['summary']['total']} total -> {args.out}")


if __name__ == "__main__":
    main()
