from __future__ import annotations

import random
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
    - 429 or 5xx -> retried with exponential backoff + jitter, honouring a
      `Retry-After` response header when present. Exhausting all attempts
      raises ProviderRateLimited carrying the last-seen `Retry-After`.
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

        if response.status_code == 429 or response.status_code >= 500:
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


def _parse_retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _sleep_backoff(attempt: int, retry_after: float | None = None) -> None:
    if retry_after is not None:
        time.sleep(retry_after)
        return
    delay = min(BASE_DELAY_SECONDS * (2 ** (attempt - 1)), MAX_DELAY_SECONDS)
    time.sleep(delay + random.uniform(0, delay * 0.25))
