import json
from pathlib import Path

import pytest

import scripts.replay_extract as replay_extract
from app.providers.base import ProviderAuthError
from app.providers.firecrawl import FirecrawlProvider


# --- shared fakes, same pattern as tests/providers/test_firecrawl.py --------

def _extract_response(parsed: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(parsed)}}]}


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200, headers: dict | None = None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


class _QueueClient:
    """Returns one canned response per call, in order. Used where the exact
    number/shape of calls doesn't matter beyond "return this payload"."""

    def __init__(self, payload: dict):
        self._payload = payload
        self.calls: list[dict] = []

    def post(self, url, headers, json):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return _FakeResponse(self._payload)

    def head(self, url, timeout=None, follow_redirects=None):
        return _FakeResponse({}, status_code=200)


class _RateLimitedThenSucceedsClient:
    """First `fail_times` calls return 429 with a Groq-shaped retry-after
    body; every call after that succeeds with `success_payload`. Mirrors
    call_with_retry's real trigger path (retry.py:56-64) so
    FirecrawlProvider._extract's first invocation exhausts MAX_ATTEMPTS and
    raises ProviderRateLimited, and a second invocation (our harness's own
    retry) succeeds.
    """

    def __init__(self, fail_times: int, success_payload: dict, retry_after_seconds: float = 14.06):
        self.fail_times = fail_times
        self.success_payload = success_payload
        self.retry_after_seconds = retry_after_seconds
        self.calls = 0

    def post(self, url, headers, json):
        self.calls += 1
        if self.calls <= self.fail_times:
            body = {
                "error": {
                    "message": (
                        f"Rate limit reached for model openai/gpt-oss-20b. "
                        f"Please try again in {self.retry_after_seconds}s."
                    )
                }
            }
            return _FakeResponse(body, status_code=429)
        return _FakeResponse(self.success_payload)

    def head(self, url, timeout=None, follow_redirects=None):
        return _FakeResponse({}, status_code=200)


def _found_payload(price: str = "10.00") -> dict:
    return _extract_response({
        "found": True, "price": float(price), "currency": "PLN", "seller": "Example Shop",
        "source_url": "https://example.com/product", "delivery_days": 2, "confidence": 0.85,
    })


def _not_found_payload() -> dict:
    return _extract_response({"found": False})


def _raw_text_for(results: list[dict]) -> str:
    """Builds a search_raw_text guaranteed to round-trip, via the same
    renderer replay_extract's parser must reverse."""
    return FirecrawlProvider._format_snippets(results)


def _source_entry(sku: str, raw_text: str, *, outcome: str, price: str | None = None) -> dict:
    entry = {"sku": sku, "name": f"Product {sku}", "ean": None, "outcome": outcome,
              "search_raw_text": raw_text}
    if outcome == "found":
        entry["offer"] = {
            "price": price, "currency": "PLN", "seller": "Old Seller",
            "source_url": "https://old.example", "delivery_days": 1,
            "confidence": 0.8, "citations": [],
        }
    return entry


SIMPLE_RESULTS = [
    {"title": "Example Shop", "description": "Cena: 89.99 zl", "url": "https://example.com/product"},
]


# --- 1. Parser round-trip ----------------------------------------------------

def test_parser_round_trips_a_synthetic_multi_result_block():
    results = [
        {"title": "Shop A", "description": "Cena: 19.99 zl", "url": "https://a.example/p"},
        {"title": "Shop B", "description": "Multi-line\ndescription\ntext", "url": "https://b.example/p"},
        {"title": "Shop C", "description": "", "url": "https://c.example/p"},
    ]
    raw_text = _raw_text_for(results)

    parsed = replay_extract.parse_and_validate(raw_text)

    assert parsed == results
    assert FirecrawlProvider._format_snippets(parsed) == raw_text


def test_parser_boundary_guard_rejects_out_of_sequence_numbered_line_inside_a_description():
    # A line that DOES start with "N. " — matching the boundary regex's
    # shape exactly — but whose N is not the next expected number must be
    # rejected as a boundary and absorbed as description content instead.
    # This is the actual guard _find_block_boundaries documents; the
    # previous version of this test used a line that never matched the
    # regex at all ("numbered-looking 5. line" doesn't start with a digit),
    # so it never reached the numeric-comparison branch — caught in review.
    #
    # The false-positive-shaped line can only land at column 0 (no leading
    # "   " indent) if it's NOT the first line of the description — the
    # first description line always carries _format_snippets's 3-space
    # indent, so it can never itself match ^\d+\. . Embedding it as the
    # SECOND line of a multi-line description puts it exactly where a real
    # boundary line would be.
    results = [
        {
            "title": "Shop A",
            "description": "first line here\n5. Something unrelated\nmore text",
            "url": "https://a.example/p",
        },
        {"title": "Shop B", "description": "normal description", "url": "https://b.example/p"},
    ]
    raw_text = _raw_text_for(results)

    parsed = replay_extract.parse_and_validate(raw_text)

    # The guard held: exactly 2 entries recovered (not 3 — the "5. "
    # line inside Shop A's description was never treated as a real
    # boundary), matching the original titles/descriptions/urls
    # byte-for-byte, including the embedded false-positive-shaped line.
    assert parsed is not None
    assert len(parsed) == 2
    assert parsed == results
    assert FirecrawlProvider._format_snippets(parsed) == raw_text


def test_parser_rejects_text_missing_the_trailing_url_line():
    # A block with only a title and description line — no url — cannot have
    # come from _format_snippets, which always emits 3 lines minimum.
    malformed = "1. Some Title\n   Some description, no url line follows"

    assert replay_extract.parse_and_validate(malformed) is None


def test_parser_rejects_text_with_wrong_entry_numbering():
    # Starts at "2." instead of "1." — _find_block_boundaries requires the
    # sequence to start at 1, so this is never accepted as a boundary at
    # all, leaving zero boundaries found (not merely a misgrouping — see
    # the note below on why a *mid-sequence* wrong number is a weaker test
    # than it looks).
    malformed = "2. Shop A\n   desc a\n   https://a.example"

    assert replay_extract.parse_and_validate(malformed) is None


def test_parser_rejects_url_line_missing_its_expected_indentation():
    # _format_snippets always prepends "   " (3 spaces) to the url line; a
    # url line with no indentation at all cannot have come from it, and
    # re-rendering the parsed structure would add indentation that wasn't
    # in the original text — a genuine byte-level round-trip mismatch,
    # unlike the "wrong numbering" case above where a rejected boundary
    # just gets silently absorbed into the surrounding description and
    # still round-trips (see parse_snippets's docstring).
    malformed = "1. Shop A\n   some description\nhttps://a.example"  # url has no leading spaces

    assert replay_extract.parse_and_validate(malformed) is None


def test_parser_handles_empty_search_raw_text():
    assert replay_extract.parse_and_validate("") == []


# --- 2. match / PRICE_CHANGED / regression_now_not_found ---------------------

def test_classification_match_when_replayed_price_equals_recorded_price(tmp_path):
    raw_text = _raw_text_for(SIMPLE_RESULTS)
    entry = _source_entry("SKU-1", raw_text, outcome="found", price="10.00")
    client = _QueueClient(_found_payload(price="10.00"))
    provider = FirecrawlProvider(api_key="unused", groq_api_key="g", client=client)
    checked: dict = {}

    status_counts = replay_extract.run_replay(
        provider, [entry], checked,
        market="PL", max_delivery_days=5, wait_cap_seconds=30, budget_hours=1.0,
        sku_filter=None, limit=None,
        out_path=tmp_path / "out.json", source_path=Path("source.json"),
    )

    assert status_counts == {"match": 1}
    assert checked["SKU-1"]["status"] == "match"
    assert checked["SKU-1"]["old_price"] == "10.00"
    assert checked["SKU-1"]["new_price"] == "10.0"


def test_classification_price_changed_when_replayed_price_differs(tmp_path):
    raw_text = _raw_text_for(SIMPLE_RESULTS)
    entry = _source_entry("SKU-1", raw_text, outcome="found", price="10.00")
    client = _QueueClient(_found_payload(price="25.50"))
    provider = FirecrawlProvider(api_key="unused", groq_api_key="g", client=client)
    checked: dict = {}

    status_counts = replay_extract.run_replay(
        provider, [entry], checked,
        market="PL", max_delivery_days=5, wait_cap_seconds=30, budget_hours=1.0,
        sku_filter=None, limit=None,
        out_path=tmp_path / "out.json", source_path=Path("source.json"),
    )

    assert status_counts == {"PRICE_CHANGED": 1}
    assert checked["SKU-1"]["status"] == "PRICE_CHANGED"
    assert checked["SKU-1"]["old_price"] == "10.00"
    assert checked["SKU-1"]["new_price"] == "25.5"


def test_classification_regression_when_replay_no_longer_finds_an_offer(tmp_path):
    raw_text = _raw_text_for(SIMPLE_RESULTS)
    entry = _source_entry("SKU-1", raw_text, outcome="found", price="10.00")
    client = _QueueClient(_not_found_payload())
    provider = FirecrawlProvider(api_key="unused", groq_api_key="g", client=client)
    checked: dict = {}

    status_counts = replay_extract.run_replay(
        provider, [entry], checked,
        market="PL", max_delivery_days=5, wait_cap_seconds=30, budget_hours=1.0,
        sku_filter=None, limit=None,
        out_path=tmp_path / "out.json", source_path=Path("source.json"),
    )

    assert status_counts == {"regression_now_not_found": 1}
    assert checked["SKU-1"]["status"] == "regression_now_not_found"
    assert checked["SKU-1"]["new_price"] is None


# --- 3. replayed_no_baseline --------------------------------------------------

@pytest.mark.parametrize("prior_outcome", ["not_found", "error"])
def test_replayed_no_baseline_for_non_found_source_entries(prior_outcome, tmp_path):
    raw_text = _raw_text_for(SIMPLE_RESULTS)
    entry = _source_entry("SKU-1", raw_text, outcome=prior_outcome)
    client = _QueueClient(_found_payload(price="42.00"))
    provider = FirecrawlProvider(api_key="unused", groq_api_key="g", client=client)
    checked: dict = {}

    status_counts = replay_extract.run_replay(
        provider, [entry], checked,
        market="PL", max_delivery_days=5, wait_cap_seconds=30, budget_hours=1.0,
        sku_filter=None, limit=None,
        out_path=tmp_path / "out.json", source_path=Path("source.json"),
    )

    assert status_counts == {"replayed_no_baseline": 1}
    assert checked["SKU-1"]["status"] == "replayed_no_baseline"
    assert checked["SKU-1"]["old_price"] is None
    assert checked["SKU-1"]["new_price"] == "42.0"


# --- 4. rate-limit retry ------------------------------------------------------

def test_rate_limited_entry_is_retried_and_eventually_resolves(monkeypatch, tmp_path):
    # NOTE: app.providers.retry and scripts.replay_extract both `import time`
    # — that binds the SAME cached module object in both places, so
    # monkeypatching "app.providers.retry.time.sleep" and
    # "scripts.replay_extract.time.sleep" separately would silently have the
    # second one clobber the first (they're the same attribute on the same
    # object). One patch on the shared "time.sleep" catches every call site.
    sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    from app.providers.retry import MAX_ATTEMPTS

    raw_text = _raw_text_for(SIMPLE_RESULTS)
    entry = _source_entry("SKU-1", raw_text, outcome="not_found")
    client = _RateLimitedThenSucceedsClient(
        fail_times=MAX_ATTEMPTS, success_payload=_found_payload(price="7.50"), retry_after_seconds=14.06,
    )
    provider = FirecrawlProvider(api_key="unused", groq_api_key="g", client=client)
    checked: dict = {}
    out_path = tmp_path / "out.json"

    status_counts = replay_extract.run_replay(
        provider, [entry], checked,
        market="PL", max_delivery_days=5, wait_cap_seconds=1500, budget_hours=6.0,
        sku_filter=None, limit=None,
        out_path=out_path, source_path=Path("source.json"),
    )

    # call_with_retry's own backoff (3 sleeps between MAX_ATTEMPTS=4 tries)
    # plus our own harness's single retry sleep = 4 total, every one of them
    # derived from the parsed retry_after (14.06s), never 0 or a bare
    # exponential-backoff guess.
    assert len(sleeps) == MAX_ATTEMPTS
    assert all(s == pytest.approx(14.06) for s in sleeps)

    assert status_counts == {"replayed_no_baseline": 1}
    assert checked["SKU-1"]["new_price"] == "7.5"
    # client.post was called MAX_ATTEMPTS times (all 429) + 1 more (success).
    assert client.calls == MAX_ATTEMPTS + 1


def test_rate_limit_wait_is_capped_by_wait_cap_seconds(monkeypatch, tmp_path):
    from app.providers.retry import MAX_ATTEMPTS, MAX_DELAY_SECONDS

    sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

    raw_text = _raw_text_for(SIMPLE_RESULTS)
    entry = _source_entry("SKU-1", raw_text, outcome="not_found")
    # retry_after (2700s = 45min) far exceeds both retry.py's own
    # MAX_DELAY_SECONDS cap and our wait_cap_seconds (30s).
    client = _RateLimitedThenSucceedsClient(
        fail_times=MAX_ATTEMPTS, success_payload=_found_payload(), retry_after_seconds=2700,
    )
    provider = FirecrawlProvider(api_key="unused", groq_api_key="g", client=client)
    checked: dict = {}

    replay_extract.run_replay(
        provider, [entry], checked,
        market="PL", max_delivery_days=5, wait_cap_seconds=30, budget_hours=6.0,
        sku_filter=None, limit=None,
        out_path=tmp_path / "out.json", source_path=Path("source.json"),
    )

    # retry.py's own 3 backoff sleeps are capped at its MAX_DELAY_SECONDS;
    # our harness's final retry sleep is capped at wait_cap_seconds (30) —
    # smaller than retry.py's own cap, so it's the one that stands out.
    assert sleeps[:3] == [MAX_DELAY_SECONDS] * 3
    assert sleeps[3] == 30


# --- 5. resumability -----------------------------------------------------------

def test_resumed_run_skips_already_checked_sku_and_processes_the_rest(tmp_path):
    raw_text_1 = _raw_text_for(SIMPLE_RESULTS)
    raw_text_2 = _raw_text_for([
        {"title": "Other Shop", "description": "Cena: 5 zl", "url": "https://other.example/p"},
    ])
    entries = [
        _source_entry("SKU-1", raw_text_1, outcome="not_found"),
        _source_entry("SKU-2", raw_text_2, outcome="not_found"),
    ]
    # SKU-1 already resolved by a prior invocation.
    checked = {"SKU-1": {"status": "replayed_no_baseline", "old_price": None, "new_price": "1.00"}}

    client = _QueueClient(_found_payload(price="3.00"))
    provider = FirecrawlProvider(api_key="unused", groq_api_key="g", client=client)

    status_counts = replay_extract.run_replay(
        provider, entries, checked,
        market="PL", max_delivery_days=5, wait_cap_seconds=30, budget_hours=1.0,
        sku_filter=None, limit=None,
        out_path=tmp_path / "out.json", source_path=Path("source.json"),
    )

    # Only SKU-2 was actually queried — one HTTP call, for SKU-2's snippets.
    assert len(client.calls) == 1
    assert status_counts == {"replayed_no_baseline": 1}
    assert checked["SKU-1"]["new_price"] == "1.00"  # untouched
    assert checked["SKU-2"]["new_price"] == "3.0"


def test_resumed_run_retries_a_prior_error_status_instead_of_skipping_it(tmp_path):
    # A prior invocation's `except Exception` catch (run_replay's broad
    # handler) is a transient failure, not a deterministic function of
    # search_raw_text like match/PRICE_CHANGED/etc — see _is_resolved's
    # docstring. Treating it as permanently resolved would silently and
    # permanently drop the SKU from every future invocation on a one-off
    # blip (this project's seed=7 hold-out DNS-outage incident is exactly
    # that failure mode). Caught in the final whole-branch review.
    raw_text = _raw_text_for(SIMPLE_RESULTS)
    entry = _source_entry("SKU-1", raw_text, outcome="not_found")
    checked = {"SKU-1": {"status": "error", "error": "RuntimeError: transient blip"}}

    client = _QueueClient(_found_payload(price="3.00"))
    provider = FirecrawlProvider(api_key="unused", groq_api_key="g", client=client)

    status_counts = replay_extract.run_replay(
        provider, [entry], checked,
        market="PL", max_delivery_days=5, wait_cap_seconds=30, budget_hours=1.0,
        sku_filter=None, limit=None,
        out_path=tmp_path / "out.json", source_path=Path("source.json"),
    )

    assert len(client.calls) == 1  # retried, not skipped
    assert status_counts == {"replayed_no_baseline": 1}
    assert checked["SKU-1"]["status"] == "replayed_no_baseline"  # overwritten, not left as "error"


@pytest.mark.parametrize("resolved_status", ["match", "PRICE_CHANGED", "regression_now_not_found",
                                              "replayed_no_baseline", "parse_failed"])
def test_resumed_run_skips_every_deterministic_status_not_just_match(resolved_status, tmp_path):
    raw_text = _raw_text_for(SIMPLE_RESULTS)
    entry = _source_entry("SKU-1", raw_text, outcome="not_found")
    checked = {"SKU-1": {"status": resolved_status}}

    client = _QueueClient(_found_payload(price="3.00"))
    provider = FirecrawlProvider(api_key="unused", groq_api_key="g", client=client)

    status_counts = replay_extract.run_replay(
        provider, [entry], checked,
        market="PL", max_delivery_days=5, wait_cap_seconds=30, budget_hours=1.0,
        sku_filter=None, limit=None,
        out_path=tmp_path / "out.json", source_path=Path("source.json"),
    )

    assert len(client.calls) == 0  # skipped, not retried
    assert status_counts == {}
    assert checked["SKU-1"]["status"] == resolved_status  # untouched


def test_main_resumes_from_an_existing_out_file(monkeypatch, tmp_path):
    raw_text_1 = _raw_text_for(SIMPLE_RESULTS)
    raw_text_2 = _raw_text_for([
        {"title": "Other Shop", "description": "Cena: 5 zl", "url": "https://other.example/p"},
    ])
    source = {
        "summary": {},
        "results": [
            _source_entry("SKU-1", raw_text_1, outcome="not_found"),
            _source_entry("SKU-2", raw_text_2, outcome="not_found"),
        ],
    }
    source_path = tmp_path / "source.json"
    source_path.write_text(json.dumps(source))

    out_path = tmp_path / "replay_source.json"
    out_path.write_text(json.dumps({
        "source": str(source_path),
        "checked": {"SKU-1": {"status": "replayed_no_baseline", "old_price": None, "new_price": "1.00"}},
    }))

    client = _QueueClient(_found_payload(price="3.00"))
    fake_provider = FirecrawlProvider(api_key="unused", groq_api_key="g", client=client)
    monkeypatch.setattr(replay_extract, "build_provider", lambda key: fake_provider)
    monkeypatch.setenv("GROQ_API_KEY", "dummy")

    replay_extract.main([
        "--source", str(source_path), "--out", str(out_path), "--budget-hours", "1.0",
    ])

    data = json.loads(out_path.read_text())
    assert set(data["checked"]) == {"SKU-1", "SKU-2"}
    assert data["checked"]["SKU-1"]["new_price"] == "1.00"  # untouched
    assert data["checked"]["SKU-2"]["new_price"] == "3.0"
    assert len(client.calls) == 1  # only SKU-2 was queried


# --- 6. wall-clock budget cutoff ----------------------------------------------

def test_budget_exhausted_before_first_attempt_stops_cleanly_leaving_entry_unresolved(monkeypatch, tmp_path):
    monkeypatch.setattr(replay_extract, "_budget_exhausted", lambda *a, **k: True)

    raw_text = _raw_text_for(SIMPLE_RESULTS)
    entry = _source_entry("SKU-1", raw_text, outcome="not_found")
    client = _QueueClient(_found_payload())
    provider = FirecrawlProvider(api_key="unused", groq_api_key="g", client=client)
    checked: dict = {}
    out_path = tmp_path / "out.json"

    status_counts = replay_extract.run_replay(
        provider, [entry], checked,
        market="PL", max_delivery_days=5, wait_cap_seconds=30, budget_hours=6.0,
        sku_filter=None, limit=None,
        out_path=out_path, source_path=Path("source.json"),
    )

    assert status_counts == {}
    assert checked == {}
    assert len(client.calls) == 0  # never even attempted
    # A valid, resumable output file is still produced by the caller's own
    # bookkeeping in this test (run_replay itself only writes on resolution,
    # so nothing to write here) — the important invariant is no exception.


def test_budget_exhausted_mid_retry_stops_without_recording_the_entry(monkeypatch, tmp_path):
    monkeypatch.setattr("time.sleep", lambda s: None)

    raw_text = _raw_text_for(SIMPLE_RESULTS)
    entry = _source_entry("SKU-1", raw_text, outcome="not_found")
    # Every call rate-limits; the harness would retry forever without the
    # budget check catching it on the second pass through the while loop.
    client = _RateLimitedThenSucceedsClient(
        fail_times=999, success_payload=_found_payload(), retry_after_seconds=1.0,
    )
    provider = FirecrawlProvider(api_key="unused", groq_api_key="g", client=client)
    checked: dict = {}
    out_path = tmp_path / "out.json"

    # Budget looks fine on the very first check (so the entry is attempted
    # and genuinely rate-limits once) but exhausted from the second check
    # onward (so the retry loop stops instead of looping forever).
    calls = {"n": 0}

    def fake_budget_exhausted(*a, **k):
        calls["n"] += 1
        return calls["n"] > 1

    monkeypatch.setattr(replay_extract, "_budget_exhausted", fake_budget_exhausted)

    status_counts = replay_extract.run_replay(
        provider, [entry], checked,
        market="PL", max_delivery_days=5, wait_cap_seconds=30, budget_hours=6.0,
        sku_filter=None, limit=None,
        out_path=out_path, source_path=Path("source.json"),
    )

    assert status_counts == {}
    assert checked == {}  # entry left unresolved, no partial/sentinel state
    assert not out_path.exists()  # nothing was ever written for it


# --- checkpoint write is atomic (crash-survival is this script's whole point) -

def test_write_output_writes_valid_json_and_leaves_no_temp_file_behind(tmp_path):
    out_path = tmp_path / "out.json"

    replay_extract._write_output(out_path, Path("source.json"), {"SKU-1": {"status": "match"}})

    data = json.loads(out_path.read_text())
    assert data == {"source": "source.json", "checked": {"SKU-1": {"status": "match"}}}
    # No leftover .out.json.tmp<pid> sibling after a successful write.
    assert list(tmp_path.glob(".out.json.tmp*")) == []


def test_write_output_never_corrupts_an_existing_file_if_the_swap_is_interrupted(monkeypatch, tmp_path):
    # Simulates a crash between "temp file written" and "renamed into
    # place" — the exact scenario the atomic write exists to survive.
    # The destination
    # must be left exactly as it was before this call — the old complete
    # content — never truncated and never partially overwritten, since
    # os.replace() is the only step that touches out_path itself.
    out_path = tmp_path / "out.json"
    original = json.dumps({"source": "source.json", "checked": {"SKU-1": {"status": "match"}}}, indent=2)
    out_path.write_text(original)

    def _boom(*a, **k):
        raise OSError("simulated crash between temp-write and rename")

    monkeypatch.setattr("os.replace", _boom)

    with pytest.raises(OSError):
        replay_extract._write_output(out_path, Path("source.json"), {"SKU-2": {"status": "match"}})

    # Destination untouched — still the OLD content, byte-for-byte.
    assert out_path.read_text() == original


# --- auth error aborts the whole run, not just one entry ---------------------

class _AuthFailsClient:
    def post(self, url, headers, json):
        return _FakeResponse({}, status_code=401)


def test_auth_error_aborts_the_run_instead_of_being_recorded_per_entry(tmp_path):
    # Mirrors provider_eval.py's identical safeguard: a rejected key fails
    # every remaining entry identically, so recording "error" per SKU and
    # continuing would just burn the rest of the invocation for nothing.
    raw_1 = _raw_text_for(SIMPLE_RESULTS)
    raw_2 = _raw_text_for([{"title": "X", "description": "d", "url": "https://x.example"}])
    entries = [
        _source_entry("SKU-1", raw_1, outcome="not_found"),
        _source_entry("SKU-2", raw_2, outcome="not_found"),
    ]
    provider = FirecrawlProvider(api_key="unused", groq_api_key="bad-key", client=_AuthFailsClient())
    checked: dict = {}
    out_path = tmp_path / "out.json"

    with pytest.raises(ProviderAuthError):
        replay_extract.run_replay(
            provider, entries, checked,
            market="PL", max_delivery_days=5, wait_cap_seconds=30, budget_hours=1.0,
            sku_filter=None, limit=None,
            out_path=out_path, source_path=Path("source.json"),
        )

    assert checked == {}  # SKU-1 never recorded as an "error" entry
    assert not out_path.exists()  # nothing was ever written


# --- misc: --skus and --limit filters ------------------------------------------

def test_sku_filter_restricts_which_entries_are_processed(tmp_path):
    raw_1 = _raw_text_for(SIMPLE_RESULTS)
    raw_2 = _raw_text_for([{"title": "X", "description": "d", "url": "https://x.example"}])
    entries = [
        _source_entry("SKU-1", raw_1, outcome="not_found"),
        _source_entry("SKU-2", raw_2, outcome="not_found"),
    ]
    client = _QueueClient(_found_payload())
    provider = FirecrawlProvider(api_key="unused", groq_api_key="g", client=client)
    checked: dict = {}

    replay_extract.run_replay(
        provider, entries, checked,
        market="PL", max_delivery_days=5, wait_cap_seconds=30, budget_hours=1.0,
        sku_filter={"SKU-2"}, limit=None,
        out_path=tmp_path / "out.json", source_path=Path("source.json"),
    )

    assert set(checked) == {"SKU-2"}


def test_limit_caps_the_number_of_new_entries_processed(tmp_path):
    entries = [
        _source_entry(f"SKU-{i}", _raw_text_for(SIMPLE_RESULTS), outcome="not_found")
        for i in range(3)
    ]
    client = _QueueClient(_found_payload())
    provider = FirecrawlProvider(api_key="unused", groq_api_key="g", client=client)
    checked: dict = {}

    replay_extract.run_replay(
        provider, entries, checked,
        market="PL", max_delivery_days=5, wait_cap_seconds=30, budget_hours=1.0,
        sku_filter=None, limit=1,
        out_path=tmp_path / "out.json", source_path=Path("source.json"),
    )

    assert len(checked) == 1
