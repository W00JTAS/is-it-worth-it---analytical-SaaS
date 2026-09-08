from __future__ import annotations

import httpx

# Bounded so one dead/slow site can't stall an entire scan. Why this exists
# at all: a search snippet can be stale — the page it was indexed from has
# since gone away — with nothing in the cached text to reveal that, so no
# prompt instruction can catch it. Only a real, live request can.
LIVENESS_TIMEOUT_SECONDS = 5.0


def is_confirmed_dead(url: str, client: httpx.Client) -> bool:
    """True only when `url` is unambiguously dead (HTTP 404) right now.

    Deliberately conservative in every other direction: a bot-block (403,
    common on Allegro and other gated marketplaces, which serve a
    challenge page to any client without a real browser fingerprint), a
    timeout, a connection error, a redirect, or any other status all
    return False.
    Rejecting an offer needs certainty; "couldn't verify" must never be
    treated the same as "confirmed dead", or this would silently drop a
    large share of genuinely good offers from bot-gated marketplaces —
    worse than the dead-link problem it's meant to fix. See this project's
    own live audit: 7/7 real Allegro URLs 403'd a plain HTTP client even
    with a spoofed user agent.
    """
    try:
        response = client.head(
            url, timeout=LIVENESS_TIMEOUT_SECONDS, follow_redirects=True,
        )
    except httpx.HTTPError:
        return False
    return response.status_code == 404
