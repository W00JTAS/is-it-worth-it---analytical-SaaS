import json
from decimal import Decimal
from pathlib import Path

import pytest

import scripts.provider_eval as provider_eval
from app.models.product import Product
from app.providers.base import OfferResult, ProviderAuthError
from app.providers.fallback import FallbackProvider
from app.providers.firecrawl import FirecrawlProvider
from app.providers.groq import GroqProvider


def _make_product(sku: str, name: str = "Product", wholesale: str = "10.00") -> Product:
    return Product(
        tenant_id="eval", source="csv", external_id=sku, variant_id=None,
        name=f"{name} {sku}", ean=None, wholesale_price=Decimal(wholesale),
        currency="PLN", category="Test",
    )


class _FakeProvider:
    """Fake PriceProvider-shaped object — mirrors test_groq.py's fake-client
    pattern but at the provider level, so run_eval/main never make a real
    HTTP call. `outcomes` maps sku -> "found" | "not_found" | an Exception
    instance to raise | an OfferResult to return verbatim. Also mimics
    GroqProvider's last_search_text attribute so --keep-raw can be tested
    without a real GroqProvider.
    """

    name = "fake"

    def __init__(self, outcomes: dict[str, object]):
        self._outcomes = outcomes
        self.calls: list[str] = []
        self.last_search_text: str | None = None

    def find_cheapest(self, product, market, max_delivery_days):
        self.calls.append(product.external_id)
        outcome = self._outcomes.get(product.external_id, "not_found")
        if isinstance(outcome, Exception):
            self.last_search_text = None
            raise outcome
        self.last_search_text = f"raw search text for {product.external_id}"
        if isinstance(outcome, OfferResult):
            return outcome
        if outcome == "found":
            return OfferResult(
                price=Decimal("9.99"), currency="PLN", seller="Seller",
                source_url="https://example.com", delivery_days=1, confidence=0.9,
                citations=(), raw_response="raw",
            )
        return None


@pytest.fixture(autouse=True)
def _isolated_results_dir(tmp_path, monkeypatch):
    """Every test gets its own results dir so nothing touches the real
    backend/scripts/eval_results/ committed fixtures, and RESULTS_DIR is a
    module-level global read at call time so monkeypatching it here reaches
    every function that references it (find_latest_result_file, main).
    """
    results_dir = tmp_path / "eval_results"
    results_dir.mkdir()
    monkeypatch.setattr(provider_eval, "RESULTS_DIR", results_dir)
    return results_dir


def _run_main(monkeypatch, argv: list[str], products: list[Product], provider: _FakeProvider):
    monkeypatch.setattr(provider_eval, "sampled_products", lambda csv_path, n, seed: products)
    monkeypatch.setattr(provider_eval, "build_provider", lambda name: provider)
    monkeypatch.setattr("sys.argv", ["provider_eval.py", *argv])
    provider_eval.main()


def _write_prior(results_dir: Path, provider: str, seed: int, n: int, ts: int, content) -> Path:
    path = results_dir / f"{provider}_seed{seed}_n{n}_{ts}.json"
    path.write_text(json.dumps(content, indent=2))
    return path


BASE_ARGV = ["--provider", "groq-compound-mini", "--seed", "1", "--sample-size", "3", "--delay-seconds", "0"]


def test_only_unresolved_legacy_shape_skips_resolved_and_merges(tmp_path, monkeypatch, capsys):
    results_dir = provider_eval.RESULTS_DIR
    prior = [
        {"sku": "A", "name": "Product A", "ean": None, "outcome": "found",
         "offer": {"price": "5.00", "currency": "PLN", "seller": "Old Seller",
                    "source_url": "https://old.example", "delivery_days": 1,
                    "confidence": 0.8, "citations": []}},
        {"sku": "B", "name": "Product B", "ean": None, "outcome": "not_found"},
    ]
    prior_path = _write_prior(results_dir, "groq-compound-mini", 1, 3, 1000, prior)

    products = [_make_product("A"), _make_product("B"), _make_product("C")]
    fake = _FakeProvider(outcomes={"B": "found", "C": "not_found"})

    _run_main(monkeypatch, [*BASE_ARGV, "--only-unresolved"], products, fake)

    # A was already found, so only B and C were actually queried this run.
    assert fake.calls == ["B", "C"]

    out_files = [p for p in results_dir.glob("groq-compound-mini_seed1_n3_*.json") if p != prior_path]
    assert len(out_files) == 1
    data = json.loads(out_files[0].read_text())
    results_by_sku = {r["sku"]: r for r in data["results"]}
    assert results_by_sku["A"] == prior[0]  # carried forward unchanged
    assert results_by_sku["B"]["outcome"] == "found"  # re-queried, now found
    assert results_by_sku["C"]["outcome"] == "not_found"


def test_only_unresolved_new_shape_skips_resolved_and_merges(monkeypatch):
    results_dir = provider_eval.RESULTS_DIR
    prior = {
        # Deliberately the pre-rename summary shape (found_rate_raw), as
        # every already-committed result file carries it: load_prior_results
        # reads only "results", so an old file must stay resumable.
        "summary": {"found": 1, "not_found": 1, "error": 0, "total": 2,
                     "found_rate_raw": 0.5, "found_rate_completed": 0.5},
        "results": [
            {"sku": "A", "name": "Product A", "ean": None, "outcome": "found",
             "offer": {"price": "5.00", "currency": "PLN", "seller": "Old Seller",
                        "source_url": "https://old.example", "delivery_days": 1,
                        "confidence": 0.8, "citations": []}},
            {"sku": "B", "name": "Product B", "ean": None, "outcome": "not_found"},
        ],
    }
    prior_path = _write_prior(results_dir, "groq-compound-mini", 1, 3, 1000, prior)

    products = [_make_product("A"), _make_product("B"), _make_product("C")]
    fake = _FakeProvider(outcomes={"B": "found", "C": "not_found"})

    _run_main(monkeypatch, [*BASE_ARGV, "--only-unresolved"], products, fake)

    assert fake.calls == ["B", "C"]

    out_files = [p for p in results_dir.glob("groq-compound-mini_seed1_n3_*.json") if p != prior_path]
    assert len(out_files) == 1
    data = json.loads(out_files[0].read_text())
    results_by_sku = {r["sku"]: r for r in data["results"]}
    assert results_by_sku["A"] == prior["results"][0]
    assert results_by_sku["B"]["outcome"] == "found"
    assert results_by_sku["C"]["outcome"] == "not_found"


def test_only_unresolved_with_no_prior_file_runs_full_sample(monkeypatch, capsys):
    products = [_make_product("A"), _make_product("B")]
    fake = _FakeProvider(outcomes={"A": "found", "B": "not_found"})

    _run_main(monkeypatch, [*BASE_ARGV, "--sample-size", "2", "--only-unresolved"], products, fake)

    assert fake.calls == ["A", "B"]
    captured = capsys.readouterr()
    assert "no prior result found" in captured.out or "no prior result file found" in captured.out


def test_written_result_file_has_summary_shape_and_found_rate_fields(monkeypatch):
    results_dir = provider_eval.RESULTS_DIR
    products = [_make_product("A"), _make_product("B"), _make_product("C")]
    fake = _FakeProvider(outcomes={
        "A": "found",
        "B": "not_found",
        "C": RuntimeError("boom"),
    })

    _run_main(monkeypatch, BASE_ARGV, products, fake)

    out_file = next(results_dir.glob("groq-compound-mini_seed1_n3_*.json"))
    data = json.loads(out_file.read_text())

    # On a full run nothing is carried forward, so this-run and cumulative
    # are identical — but both are still emitted, and labelled, so a reader
    # of the file can never mistake one for the other.
    assert data["summary"] == {
        "mode": "full",
        "prior_file": None,
        "found": 1, "not_found": 1, "error": 1, "total": 3,
        "carried_forward": 0,
        "queried_this_run": 3,
        "found_this_run": 1, "not_found_this_run": 1, "error_this_run": 1,
        "found_rate_cumulative": pytest.approx(1 / 3),
        "found_rate_this_run": pytest.approx(1 / 3),
        "found_rate_completed": pytest.approx(0.5),  # found / (found + not_found), errors excluded
    }
    assert "found_rate_raw" not in data["summary"]
    assert {r["outcome"] for r in data["results"]} == {"found", "not_found", "error"}


def test_only_unresolved_summary_separates_this_run_from_cumulative(monkeypatch, capsys):
    # The plan's first measurement safeguard ("Uczciwość pomiaru"): a resumed
    # run's inflated cumulative rate must never be readable as a single-run
    # rate comparable with the historical baselines.
    results_dir = provider_eval.RESULTS_DIR
    prior = [
        {"sku": "A", "name": "Product A", "ean": None, "outcome": "found",
         "offer": {"price": "5.00", "currency": "PLN", "seller": "Old Seller",
                    "source_url": "https://old.example", "delivery_days": 1,
                    "confidence": 0.8, "citations": []}},
        {"sku": "B", "name": "Product B", "ean": None, "outcome": "not_found"},
        {"sku": "C", "name": "Product C", "ean": None, "outcome": "not_found"},
    ]
    prior_path = _write_prior(results_dir, "groq-compound-mini", 1, 4, 1000, prior)

    products = [_make_product("A"), _make_product("B"), _make_product("C"), _make_product("D")]
    fake = _FakeProvider(outcomes={"B": "found", "C": "not_found", "D": RuntimeError("boom")})

    _run_main(monkeypatch, [*BASE_ARGV, "--sample-size", "4", "--only-unresolved"], products, fake)

    out_files = [p for p in results_dir.glob("groq-compound-mini_seed1_n4_*.json") if p != prior_path]
    summary = json.loads(out_files[0].read_text())["summary"]

    assert summary["mode"] == "only-unresolved"
    assert summary["prior_file"] == prior_path.name
    assert summary["carried_forward"] == 1  # A carried forward, untouched
    assert summary["queried_this_run"] == 3  # B, C, D
    # Cumulative counts the carried-forward A; this-run does not.
    assert summary["total"] == 4
    assert summary["found"] == 2
    assert summary["found_rate_cumulative"] == pytest.approx(0.5)
    assert summary["found_this_run"] == 1
    assert summary["not_found_this_run"] == 1
    assert summary["error_this_run"] == 1
    assert summary["found_rate_this_run"] == pytest.approx(1 / 3)

    out = capsys.readouterr().out
    assert "cumulative" in out
    assert "this run" in out


def test_only_unresolved_summary_when_nothing_left_to_query(monkeypatch, capsys):
    results_dir = provider_eval.RESULTS_DIR
    prior = [
        {"sku": "A", "name": "Product A", "ean": None, "outcome": "found"},
        {"sku": "B", "name": "Product B", "ean": None, "outcome": "found"},
    ]
    prior_path = _write_prior(results_dir, "groq-compound-mini", 1, 2, 1000, prior)

    products = [_make_product("A"), _make_product("B")]
    fake = _FakeProvider(outcomes={})

    _run_main(monkeypatch, [*BASE_ARGV, "--sample-size", "2", "--only-unresolved"], products, fake)

    assert fake.calls == []
    out_files = [p for p in results_dir.glob("groq-compound-mini_seed1_n2_*.json") if p != prior_path]
    summary = json.loads(out_files[0].read_text())["summary"]

    assert summary["queried_this_run"] == 0
    assert summary["carried_forward"] == 2
    # Never 0.0 or 1.0: nothing was measured this run, so there is no
    # single-run rate to report.
    assert summary["found_rate_this_run"] is None
    assert summary["found_rate_cumulative"] == pytest.approx(1.0)


def test_found_rate_completed_is_null_when_nothing_completed(monkeypatch):
    results_dir = provider_eval.RESULTS_DIR
    products = [_make_product("A")]
    fake = _FakeProvider(outcomes={"A": RuntimeError("boom")})

    _run_main(monkeypatch, [*BASE_ARGV, "--sample-size", "1"], products, fake)

    out_file = next(results_dir.glob("groq-compound-mini_seed1_n1_*.json"))
    data = json.loads(out_file.read_text())

    assert data["summary"]["found_rate_completed"] is None


def test_keep_raw_flag_on_captures_search_raw_text(monkeypatch):
    results_dir = provider_eval.RESULTS_DIR
    products = [_make_product("A"), _make_product("B")]
    fake = _FakeProvider(outcomes={"A": "found", "B": "not_found"})

    _run_main(monkeypatch, [*BASE_ARGV, "--sample-size", "2", "--keep-raw"], products, fake)

    out_file = next(results_dir.glob("groq-compound-mini_seed1_n2_*.json"))
    data = json.loads(out_file.read_text())
    for entry in data["results"]:
        assert entry["search_raw_text"] == f"raw search text for {entry['sku']}"


def test_keep_raw_flag_off_omits_search_raw_text(monkeypatch):
    results_dir = provider_eval.RESULTS_DIR
    products = [_make_product("A"), _make_product("B")]
    fake = _FakeProvider(outcomes={"A": "found", "B": "not_found"})

    _run_main(monkeypatch, [*BASE_ARGV, "--sample-size", "2"], products, fake)

    out_file = next(results_dir.glob("groq-compound-mini_seed1_n2_*.json"))
    data = json.loads(out_file.read_text())
    for entry in data["results"]:
        assert "search_raw_text" not in entry


def test_build_provider_groq_plus_firecrawl_returns_fallback_wrapping_both(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "dummy-groq-key")
    monkeypatch.setenv("FIRECRAWL_API_KEY", "dummy-firecrawl-key")

    provider = provider_eval.build_provider("groq+firecrawl")

    assert isinstance(provider, FallbackProvider)
    assert isinstance(provider.primary, GroqProvider)
    assert isinstance(provider.secondary, FirecrawlProvider)
    assert provider.primary._api_key == "dummy-groq-key"
    assert provider.secondary._api_key == "dummy-firecrawl-key"
    assert provider.secondary._groq_api_key == "dummy-groq-key"
    assert provider.name == "groq+firecrawl"


def test_build_provider_groq_plus_firecrawl_without_firecrawl_key_raises_keyerror(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "dummy-groq-key")
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)

    with pytest.raises(KeyError):
        provider_eval.build_provider("groq+firecrawl")


def test_auth_error_aborts_the_run_instead_of_being_recorded_as_an_error_outcome(monkeypatch):
    # base.py's ProviderAuthError docstring: a rejected key means every other
    # call fails identically, so cycling through the rest of the sample only
    # burns the scarce daily budget proving the key is still bad.
    results_dir = provider_eval.RESULTS_DIR
    products = [_make_product("A"), _make_product("B"), _make_product("C")]
    fake = _FakeProvider(outcomes={"A": "found", "B": ProviderAuthError("bad key")})

    with pytest.raises(ProviderAuthError):
        _run_main(monkeypatch, BASE_ARGV, products, fake)

    assert fake.calls == ["A", "B"]  # C never attempted
    assert list(results_dir.glob("*.json")) == []  # no partial result file written


def test_run_eval_reraises_auth_error_without_recording_an_entry():
    fake = _FakeProvider(outcomes={"A": ProviderAuthError("bad key")})

    with pytest.raises(ProviderAuthError):
        provider_eval.run_eval(
            fake, [_make_product("A")], market="PL", max_delivery_days=5, delay_seconds=0,
        )


def test_found_entry_below_wholesale_floor_is_flagged_suspiciously_low(monkeypatch):
    # Eval-side plausibility floor: an offer at 1% of the wholesale price is
    # almost certainly an extraction error (a shipping cost, an accessory's
    # price off the same page), so the manual spot-check should start here.
    results_dir = provider_eval.RESULTS_DIR
    cheap = OfferResult(
        price=Decimal("1.00"), currency="PLN", seller="Seller",
        source_url="https://example.com", delivery_days=1, confidence=0.9,
        citations=(), raw_response="raw",
    )
    products = [_make_product("A", wholesale="500.00"), _make_product("B", wholesale="500.00")]
    fake = _FakeProvider(outcomes={"A": cheap, "B": "found"})  # B: 9.99 vs 500 -> ratio 0.02

    _run_main(monkeypatch, [*BASE_ARGV, "--sample-size", "2"], products, fake)

    out_file = next(results_dir.glob("groq-compound-mini_seed1_n2_*.json"))
    by_sku = {r["sku"]: r for r in json.loads(out_file.read_text())["results"]}
    assert by_sku["A"]["price_flag"] == "suspiciously_low"
    assert by_sku["B"]["price_flag"] == "suspiciously_low"


def test_plausible_found_entry_carries_no_price_flag(monkeypatch):
    results_dir = provider_eval.RESULTS_DIR
    products = [_make_product("A", wholesale="10.00")]  # offer is 9.99 -> ratio ~1.0
    fake = _FakeProvider(outcomes={"A": "found"})

    _run_main(monkeypatch, [*BASE_ARGV, "--sample-size", "1"], products, fake)

    out_file = next(results_dir.glob("groq-compound-mini_seed1_n1_*.json"))
    entry = json.loads(out_file.read_text())["results"][0]
    assert "price_flag" not in entry


def test_price_flag_helper_boundaries():
    def offer_at(price: str) -> OfferResult:
        return OfferResult(
            price=Decimal(price), currency="PLN", seller="S",
            source_url="https://example.com", delivery_days=1, confidence=0.5,
            citations=(), raw_response="raw",
        )

    product = _make_product("A", wholesale="100.00")  # threshold = 10.00

    assert provider_eval.price_flag(offer_at("9.99"), product) == "suspiciously_low"
    assert provider_eval.price_flag(offer_at("10.00"), product) is None  # exactly at the floor
    assert provider_eval.price_flag(offer_at("250.00"), product) is None


def test_find_latest_result_file_ignores_files_without_an_integer_timestamp():
    results_dir = provider_eval.RESULTS_DIR
    (results_dir / "groq-compound-mini_seed1_n3_1000.json").write_text("[]")
    (results_dir / "groq-compound-mini_seed1_n3_2000.json").write_text("[]")
    # A hand-renamed backup: matches the glob, but int() on its trailing
    # segment would raise and abort the whole run before a single call.
    (results_dir / "groq-compound-mini_seed1_n3_2000_backup.json").write_text("[]")

    latest = provider_eval.find_latest_result_file("groq-compound-mini", 1, 3)

    assert latest is not None
    assert latest.name == "groq-compound-mini_seed1_n3_2000.json"


def test_zero_sample_size_does_not_crash_the_final_print(monkeypatch, capsys):
    fake = _FakeProvider(outcomes={})

    _run_main(monkeypatch, [*BASE_ARGV, "--sample-size", "0"], [], fake)

    out = capsys.readouterr().out
    assert "0/0 found" in out
