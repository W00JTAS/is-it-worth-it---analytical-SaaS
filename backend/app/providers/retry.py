from __future__ import annotations

import random
import re
import time
from typing import Callable

import httpx

from app.providers.base import ProviderAuthError, ProviderRateLimited

# 4 attempts total (1 initial + 3 retries). At 30 RPM this stays well inside
# a single lookup's time budget even in the worst case; more attempts would
# just burn Groq's 250/day request budget faster for no better odds.
MAX_ATTEMPTS = 4
BASE_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 20.0


def call_with_retry(send: Callable[[], httpx.Response]) -> httpx.Response:
    """Calls `send()` up to MAX_ATTEMPTS times.

    - 401/403 -> raises ProviderAuthError immediately, no retry: a bad key
      never gets better by waiting, and retrying it once per product across
      a 17,500-product scan would waste the whole attempt budget on a
      failure the first response already fully diagnosed.
    - 413, 429, or 5xx -> retried with exponential backoff + jitter, honouring
      a `Retry-After` response header when present, falling back to parsing a
      suggested wait out of the JSON error body when the header is absent
      (Groq never sets the header — see `_parse_retry_after_from_body`).
      Exhausting all attempts raises ProviderRateLimited carrying the
      last-seen retry-after. 413 is
      grouped here deliberately: observed live against Groq's compound-mini,
      an identical, correctly-sized request that got a 413 succeeded moments
      later unchanged — a transiently overloaded backend, not a genuine
      oversized-payload client error.
    - any other non-2xx -> treated as permanent; raises the response's own
      `httpx.HTTPStatusError` via `raise_for_status()`, not retried.
    - transport-level errors (ConnectError, ReadTimeout, ...) are retried
      the same as 5xx, and re-raised as-is if attempts are exhausted.
    """
    last_retry_after: float | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = send()
        except httpx.HTTPError:
            if attempt == MAX_ATTEMPTS:
                raise
            _sleep_backoff(attempt)
            continue

        if response.status_code in (401, 403):
            raise ProviderAuthError(f"provider rejected credentials: HTTP {response.status_code}")

        if response.status_code in (413, 429) or response.status_code >= 500:
            last_retry_after = _parse_retry_after(response)
            if attempt == MAX_ATTEMPTS:
                raise ProviderRateLimited(
                    f"provider rate-limited after {MAX_ATTEMPTS} attempts",
                    retry_after=last_retry_after,
                )
            _sleep_backoff(attempt, retry_after=last_retry_after)
            continue

        response.raise_for_status()
        return response

    raise AssertionError("unreachable: loop always returns or raises")


_BODY_RETRY_AFTER_RE = re.compile(
    r"try again in (?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?", re.IGNORECASE
)


def _parse_retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is not None:
        try:
            return float(value)
        except ValueError:
            pass
    return _parse_retry_after_from_body(response)


def _parse_retry_after_from_body(response: httpx.Response) -> float | None:
    """Groq does not set the Retry-After header on 429s — the suggested wait
    (e.g. "Please try again in 14.06s" or "...in 45m0s") is only in the JSON
    error body's `error.message`. Parsing vendor prose is inherently fragile
    — the wording is undocumented and can change without notice — so this is
    deliberately best-effort: any parse failure just falls back to the
    existing exponential backoff, same as before this existed.
    """
    try:
        message = response.json()["error"]["message"]
    except Exception:
        return None
    if not isinstance(message, str):
        return None
    match = _BODY_RETRY_AFTER_RE.search(message)
    if not match or not any(match.groups()):
        return None
    hours, minutes, seconds = (float(g) if g else 0.0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _sleep_backoff(attempt: int, retry_after: float | None = None) -> None:
    if retry_after is not None:
        time.sleep(min(retry_after, MAX_DELAY_SECONDS))
        return
    delay = min(BASE_DELAY_SECONDS * (2 ** (attempt - 1)), MAX_DELAY_SECONDS)
    time.sleep(delay + random.uniform(0, delay * 0.25))
