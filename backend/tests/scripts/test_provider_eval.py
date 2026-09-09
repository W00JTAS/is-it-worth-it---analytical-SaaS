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


def _offer_at(price: str, **overrides) -> OfferResult:
    fields = dict(
        price=Decimal(price), currency="PLN", seller="S",
        source_url="https://example.com", delivery_days=1, confidence=0.5,
        citations=(), raw_response="raw",
    )
    fields.update(overrides)
    return OfferResult(**fields)


# Real, confirmed-bad snippet (SKU DLZZOUKLA0055, found 2026-09-08):
# the extracted price 365.85 is immediately (across only a currency symbol
# and a period) followed by "bez VAT" qualifying THAT SAME number.
NET_PRICE_FIXTURE_BIRD_CAGE = (
    "9. ZOLUX Klatka dla ptaków Neo JILI H80 kol. szary - Takwiele.pl\n"
    "   Czas wysyłki: 24 godziny. 365,85 zł. Cena 365,85 zł. bez VAT. "
    "Najniższa cena z 30 dni przed obniżką: 347,55 zł. "
    "Promocja trwa do %s. 449,99 zł. Cena 449,99 zł.\n"
    "   https://takwiele.pl/pl/p/ZOLUX-Klatka-dla-ptakow-Neo-JILI-H80-kol.-szary/16460"
    "?srsltid=AfmBOorA2nSoqfaGKbIpz4WGwX6dw2RmjVZfGQbdS4OHV4ZqaowQrxPS"
)

# Real, confirmed-GOOD, browser-verified snippet (SKU GAR OPAL ARTISAN KPL):
# the extracted price 279.99 is the GROSS/"brutto" price and is immediately
# followed by "PLNCena netto 227,63 PLN" — "netto" here qualifies the
# DIFFERENT, following number 227,63, not 279.99. This is the exact known
# false positive a naive "does 'netto' appear nearby" check would produce.
NET_PRICE_FIXTURE_GARDEROBA = (
    "10. GARDEROBA OPAL ARTISAN KOMPLET - Meble przedpokojowe\n"
    "   Cena brutto 279,99 PLNCena netto 227,63 PLN. Dostawa ok. 5 dni. "
    "Dodaj do koszyka · GARDEROBA DUO SONOMA ...\n"
    "   https://primavo.pl/produkt/garderoba-opal-artisan-komplet-meble-przedpokojowe"
)


def test_net_price_flag_flags_the_bird_cage_net_price_case():
    assert provider_eval.net_price_flag(
        Decimal("365.85"), NET_PRICE_FIXTURE_BIRD_CAGE,
    ) == "net_price"


def test_net_price_flag_does_not_flag_the_garderoba_false_positive_case():
    # This assertion is the one that matters: it locks in the known false
    # positive (a "netto" nearby that belongs to a DIFFERENT number).
    assert provider_eval.net_price_flag(
        Decimal("279.99"), NET_PRICE_FIXTURE_GARDEROBA,
    ) is None


@pytest.mark.parametrize("marker", [
    "bez VAT", "netto", "bez podatku", "excl. VAT", "excl VAT", "ex VAT", "ex. VAT",
])
def test_net_price_flag_covers_every_observed_marker_phrase(marker):
    text = f"Some product. Cena 42,00 zł. {marker}. Free shipping."
    assert provider_eval.net_price_flag(Decimal("42.00"), text) == "net_price"


def test_net_price_flag_normalizes_polish_thousands_separator_spaces():
    # Real captured data writes higher amounts with a normal space AND with
    # thin (U+2009), non-breaking (U+00A0) and narrow-no-break (U+202F)
    # space characters as the thousands separator.
    for space in (" ", " ", " ", " "):
        text = f"Cena 2{space}779,00 zł. bez VAT."
        assert provider_eval.net_price_flag(Decimal("2779.00"), text) == "net_price", \
            f"failed for separator {space!r}"


def test_net_price_flag_matches_comma_decimal_form_against_dot_stored_price():
    # Offers store price as Decimal("365.85") (dot); the snippet always
    # writes the Polish comma form.
    text = "Cena 365,85 zł. bez VAT."
    assert provider_eval.net_price_flag(Decimal("365.85"), text) == "net_price"


def test_net_price_flag_returns_none_when_search_text_is_missing():
    assert provider_eval.net_price_flag(Decimal("10.00"), None) is None
    assert provider_eval.net_price_flag(Decimal("10.00"), "") is None


def test_net_price_flag_does_not_match_a_price_that_is_a_substring_of_a_bigger_number():
    # 9,99 must not match inside 19,99 — a plain substring search would.
    text = "Cena 19,99 zł. bez VAT."
    assert provider_eval.net_price_flag(Decimal("9.99"), text) is None


def test_net_price_flag_ignores_a_net_marker_nowhere_near_the_extracted_price():
    # "netto" is present in the text, but sits far past the lookahead window
    # this heuristic uses — a marker only counts when it (almost)
    # immediately follows the extracted price.
    filler = "x" * 80
    text = f"Cena 42,00 zł. {filler} netto na zupełnie inny temat."
    assert provider_eval.net_price_flag(Decimal("42.00"), text) is None


def test_run_eval_wires_net_price_flag_into_the_found_entry():
    class _RawTextProvider:
        name = "fake"

        def __init__(self, offer, raw_text):
            self._offer = offer
            self.last_search_text = raw_text

        def find_cheapest(self, product, market, max_delivery_days):
            return self._offer

    offer = _offer_at("365.85", seller="Takwiele.pl")
    provider = _RawTextProvider(offer, NET_PRICE_FIXTURE_BIRD_CAGE)
    product = _make_product("A", wholesale="2000.00")  # keep price_flag out of the way (threshold 200)

    results = provider_eval.run_eval(
        provider, [product], market="PL", max_delivery_days=5, delay_seconds=0,
    )

    assert results[0]["net_price_flag"] == "net_price"
    assert "price_flag" not in results[0]  # independent of the wholesale-ratio flag


def test_run_eval_does_not_set_net_price_flag_for_the_garderoba_case():
    class _RawTextProvider:
        name = "fake"

        def __init__(self, offer, raw_text):
            self._offer = offer
            self.last_search_text = raw_text

        def find_cheapest(self, product, market, max_delivery_days):
            return self._offer

    offer = _offer_at("279.99", seller="Primavo.pl")
    provider = _RawTextProvider(offer, NET_PRICE_FIXTURE_GARDEROBA)
    product = _make_product("A", wholesale="5000.00")

    results = provider_eval.run_eval(
        provider, [product], market="PL", max_delivery_days=5, delay_seconds=0,
    )

    assert "net_price_flag" not in results[0]


def test_run_eval_net_price_flag_works_even_without_keep_raw(monkeypatch, capsys):
    # The flag must surface on an ordinary live run, not only when --keep-raw
    # is also passed — --keep-raw only controls whether search_raw_text is
    # persisted into the written file.
    results_dir = provider_eval.RESULTS_DIR
    products = [_make_product("A", wholesale="5000.00")]

    class _FakeNetPriceProvider:
        name = "fake"

        def __init__(self):
            self.last_search_text = NET_PRICE_FIXTURE_BIRD_CAGE

        def find_cheapest(self, product, market, max_delivery_days):
            return _offer_at("365.85", seller="Takwiele.pl")

    fake = _FakeNetPriceProvider()
    _run_main(monkeypatch, [*BASE_ARGV, "--sample-size", "1"], products, fake)

    out_file = next(results_dir.glob("groq-compound-mini_seed1_n1_*.json"))
    data = json.loads(out_file.read_text())
    entry = data["results"][0]
    assert entry["net_price_flag"] == "net_price"
    assert "search_raw_text" not in entry  # keep-raw was NOT passed

    out = capsys.readouterr().out
    assert "net_price" in out


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
