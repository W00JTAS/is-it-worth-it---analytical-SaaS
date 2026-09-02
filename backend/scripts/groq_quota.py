"""Groq quota probe: makes one minimal chat-completion call against
groq/compound-mini and reports the x-ratelimit-* headers Groq returns on
every response (success or error).

Exists because nothing checked remaining quota before a batch of live
lookups — see `.claude/rules/groq-compound-free-tier-reliability.md`, which
found the real daily bottleneck is an undocumented token-per-day limit on an
internal orchestration model (llama-3.3-70b-versatile, 100,000 tokens/day),
not the advertised 250 requests/day on compound-mini itself. That rule file
prescribes checking `x-ratelimit-remaining-*` headers before every eval run;
this script is that check.

Usage (from `backend/`, after sourcing ../.env.local per README.md):

    set -a && source ../.env.local && set +a
    .venv/bin/python scripts/groq_quota.py

Exit code: 0 if the probe call itself succeeded (regardless of how much
budget remains), 1 if it failed (429/5xx/etc — the "don't even try a batch
today" signal). Intended for `scripts/groq_quota.py || echo "skip Groq
today"` in a later eval step.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.providers.groq import API_URL, SEARCH_MODEL  # noqa: E402

# Assumption: a real lookup (search call + extract call) costs roughly
# ~2000 tokens on the search-orchestration model that gates the daily
# budget (llama-3.3-70b-versatile) — see
# .claude/rules/groq-compound-free-tier-reliability.md, which measured real
# per-lookup costs in the ~2000-3300 tokens range across two days of live
# evaluation before this session's Task 3 shortened the search prompt. This
# is a rough estimate for a "should I even try a batch today" signal, not a
# measured guarantee.
TOKENS_PER_LOOKUP_ESTIMATE = 2000


@dataclass
class ProbeResult:
    """Result of one probe call. `ratelimit_headers` holds every response
    header whose name starts with x-ratelimit- (case-insensitively), keyed
    exactly as returned by Groq — not hardcoded to the currently-documented
    names, in case Groq exposes more.
    """

    success: bool
    status_code: int | None
    ratelimit_headers: dict[str, str] = field(default_factory=dict)
    error_message: str | None = None


def probe(client: httpx.Client, api_key: str) -> ProbeResult:
    """Makes one minimal chat-completion call against groq/compound-mini.
    Never raises on a non-2xx response — that's the whole point of a quota
    probe, since a 429 here is an expected, informative outcome, not a bug.
    """
    response = client.post(
        API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": SEARCH_MODEL,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
        },
    )

    ratelimit_headers = {
        k: v for k, v in response.headers.items() if k.lower().startswith("x-ratelimit-")
    }

    if 200 <= response.status_code < 300:
        return ProbeResult(
            success=True, status_code=response.status_code, ratelimit_headers=ratelimit_headers,
        )

    error_message = None
    try:
        error_message = response.json().get("error", {}).get("message")
    except Exception:
        pass

    return ProbeResult(
        success=False,
        status_code=response.status_code,
        ratelimit_headers=ratelimit_headers,
        error_message=error_message,
    )


# Why the OK verdict is worded as an upper bound rather than a prediction:
# x-ratelimit-remaining-tokens is compound-mini's OWN token counter, but the
# binding daily limit measured in
# .claude/rules/groq-compound-free-tier-reliability.md is an undocumented
# tokens-per-day budget on an INTERNAL orchestration model
# (llama-3.3-70b-versatile, 100,000/day) that this header does not reflect at
# all — real runs died with 86/250 requests and a healthy-looking token
# header still showing. So the number below can look fine on an already-dead
# day; the probe call succeeding is the only strong signal here.
_UPPER_BOUND_CAVEAT = (
    "upper bound only — does not reflect Groq's internal per-model daily "
    "limit, see .claude/rules/groq-compound-free-tier-reliability.md; the "
    "probe call itself succeeding is the only strong signal here"
)


def verdict(result: ProbeResult) -> str:
    if not result.success:
        return "EXHAUSTED - quota errored on the probe call itself"

    remaining = result.ratelimit_headers.get("x-ratelimit-remaining-tokens")
    if remaining is None:
        return "OK - probe succeeded, x-ratelimit-remaining-tokens header not present"
    try:
        estimated = int(remaining) // TOKENS_PER_LOOKUP_ESTIMATE
    except ValueError:
        return f"OK - probe succeeded, x-ratelimit-remaining-tokens header unparseable ({remaining!r})"
    return (
        f"OK - ~{estimated} lookups possible under this header's counter alone "
        f"({_UPPER_BOUND_CAVEAT})"
    )


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise SystemExit("GROQ_API_KEY is not set in the environment")

    client = httpx.Client(timeout=30.0)
    result = probe(client, api_key)

    print(f"probe call: {'OK' if result.success else 'FAILED'} (HTTP {result.status_code})")
    for key in sorted(result.ratelimit_headers):
        print(f"  {key}: {result.ratelimit_headers[key]}")
    if result.error_message:
        print(f"  error.message: {result.error_message}")

    print(verdict(result))
    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
