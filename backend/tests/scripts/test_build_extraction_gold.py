import json
from pathlib import Path

import scripts.build_extraction_gold as build_extraction_gold


def _write_source(path: Path, results: list[dict]) -> Path:
    path.write_text(json.dumps({"summary": {"unrelated": "this run's own summary"}, "results": results}))
    return path


def test_is_gold_candidate_keeps_only_found_with_raw_text_and_no_suspicious_flag():
    found_clean = {"sku": "A", "outcome": "found", "search_raw_text": "1. x\n   y\n   z",
                   "offer": {"price": "10.00"}}
    found_no_flag_key = {"sku": "B", "outcome": "found", "search_raw_text": "1. x\n   y\n   z",
                          "price_flag": None, "offer": {"price": "5.00"}}
    found_suspicious = {"sku": "C", "outcome": "found", "search_raw_text": "1. x\n   y\n   z",
                         "price_flag": "suspiciously_low", "offer": {"price": "0.01"}}
    found_no_raw_text = {"sku": "D", "outcome": "found", "search_raw_text": None,
                          "offer": {"price": "10.00"}}
    found_empty_raw_text = {"sku": "E", "outcome": "found", "search_raw_text": "",
                             "offer": {"price": "10.00"}}
    not_found = {"sku": "F", "outcome": "not_found", "search_raw_text": "1. x\n   y\n   z"}
    error = {"sku": "G", "outcome": "error", "search_raw_text": "1. x\n   y\n   z"}
    found_no_offer_key = {"sku": "H", "outcome": "found", "search_raw_text": "1. x\n   y\n   z"}

    assert build_extraction_gold.is_gold_candidate(found_clean) is True
    assert build_extraction_gold.is_gold_candidate(found_no_flag_key) is True
    assert build_extraction_gold.is_gold_candidate(found_no_offer_key) is True
    assert build_extraction_gold.is_gold_candidate(found_suspicious) is False
    assert build_extraction_gold.is_gold_candidate(found_no_raw_text) is False
    assert build_extraction_gold.is_gold_candidate(found_empty_raw_text) is False
    assert build_extraction_gold.is_gold_candidate(not_found) is False
    assert build_extraction_gold.is_gold_candidate(error) is False


def test_is_gold_candidate_rejects_price_flag_at_top_level_matching_provider_eval_output_shape():
    # provider_eval.py writes price_flag as a sibling of "offer", not nested
    # inside it (scripts/provider_eval.py:460-462) — a candidate carrying it
    # at the top level must be excluded even though "offer" itself carries
    # no flag at all.
    suspicious_low_top_level = {"sku": "I", "outcome": "found", "search_raw_text": "1. x\n   y\n   z",
                                 "price_flag": "suspiciously_low", "offer": {"price": "0.01"}}
    clean_top_level = {"sku": "K", "outcome": "found", "search_raw_text": "1. x\n   y\n   z",
                        "offer": {"price": "10.00"}}

    assert build_extraction_gold.is_gold_candidate(suspicious_low_top_level) is False
    assert build_extraction_gold.is_gold_candidate(clean_top_level) is True


def test_is_gold_candidate_excludes_net_of_vat_prices_recomputed_from_raw_text():
    # net_price_flag isn't reliably pre-stored on an entry: both source files
    # this script currently reads (groq+firecrawl_seed42_n25_1788352269.json,
    # groq+firecrawl_seed7_n25_1788358094.json) were captured before
    # net_price_flag() existed as a feature in provider_eval.py, so neither
    # entry carries the key at all — trusting a stored field would silently
    # let both known-bad entries (DLZZOUKLA0055, 960-001459) back into the
    # fixture. Recomputing straight from offer.price + search_raw_text closes
    # that gap regardless of when/whether the source file stored the flag.
    # Raw text pattern is 960-001459's own real snippet, confirmed live
    # 2026-09-09: displayed price is 354,99 zł, 288,61 is the "bez VAT" figure.
    net_price_entry = {
        "sku": "J", "outcome": "found",
        "search_raw_text": ("10. Some Store\n   Cena 288,61 zł. bez VAT. Najniższa cena z 30 dni "
                             "przed obniżką: 356,90 zł. Promocja trwa do %s. 354,99 zł. "
                             "Cena 354,99 zł."),
        "offer": {"price": "288.61"},
    }
    gross_price_entry = {
        "sku": "K", "outcome": "found",
        "search_raw_text": "1. Some Store\n   Cena 354,99 zł.",
        "offer": {"price": "354.99"},
    }

    assert build_extraction_gold.is_gold_candidate(net_price_entry) is False
    assert build_extraction_gold.is_gold_candidate(gross_price_entry) is True


def test_build_gold_entries_merges_across_sources_and_counts_per_file(tmp_path):
    source_a = _write_source(tmp_path / "a.json", [
        {"sku": "A1", "outcome": "found", "search_raw_text": "1. x\n   y\n   z", "offer": {"price": "10.00"}},
        {"sku": "A2", "outcome": "not_found", "search_raw_text": None},
        {"sku": "A3", "outcome": "found", "search_raw_text": "1. x\n   y\n   z",
         "price_flag": "suspiciously_low", "offer": {"price": "1.00"}},
    ])
    source_b = _write_source(tmp_path / "b.json", [
        {"sku": "B1", "outcome": "found", "search_raw_text": "1. p\n   q\n   r", "offer": {"price": "20.00"}},
        {"sku": "B2", "outcome": "error", "search_raw_text": "1. p\n   q\n   r"},
    ])

    kept, counts_by_source = build_extraction_gold.build_gold_entries([source_a, source_b])

    assert [e["sku"] for e in kept] == ["A1", "B1"]
    assert counts_by_source == {"a.json": 1, "b.json": 1}


def test_build_gold_payload_shape_matches_replay_extract_expectations(tmp_path):
    source_a = _write_source(tmp_path / "a.json", [
        {"sku": "A1", "outcome": "found", "search_raw_text": "1. x\n   y\n   z", "offer": {"price": "10.00"}},
    ])
    source_b = _write_source(tmp_path / "b.json", [
        {"sku": "B1", "outcome": "found", "search_raw_text": "1. p\n   q\n   r", "offer": {"price": "20.00"}},
        {"sku": "B2", "outcome": "found", "search_raw_text": "1. p\n   q\n   r",
         "price_flag": "suspiciously_low", "offer": {"price": "0.50"}},
    ])

    payload = build_extraction_gold.build_gold_payload([source_a, source_b])

    assert payload["summary"]["source_files"] == ["a.json", "b.json"]
    assert payload["summary"]["counts_by_source"] == {"a.json": 1, "b.json": 1}
    assert payload["summary"]["total"] == 2
    assert [e["sku"] for e in payload["results"]] == ["A1", "B1"]
    # replay_extract.py reads exactly {"summary": ..., "results": [...]} with
    # "found"-outcome entries carrying "search_raw_text" and "offer.price".
    for entry in payload["results"]:
        assert entry["outcome"] == "found"
        assert entry["search_raw_text"]
        assert entry["offer"]["price"]


def test_main_writes_fixture_file_and_prints_one_line_summary(tmp_path, monkeypatch, capsys):
    source_a = _write_source(tmp_path / "a.json", [
        {"sku": "A1", "outcome": "found", "search_raw_text": "1. x\n   y\n   z", "offer": {"price": "10.00"}},
        {"sku": "A2", "outcome": "not_found", "search_raw_text": None},
    ])
    source_b = _write_source(tmp_path / "b.json", [
        {"sku": "B1", "outcome": "found", "search_raw_text": "1. p\n   q\n   r", "offer": {"price": "20.00"}},
    ])
    out_path = tmp_path / "out" / "extraction_gold.json"

    build_extraction_gold.main(["--sources", str(source_a), str(source_b), "--out", str(out_path)])

    assert out_path.exists()
    data = json.loads(out_path.read_text())
    assert data["summary"]["total"] == 2
    assert [e["sku"] for e in data["results"]] == ["A1", "B1"]

    out = capsys.readouterr().out
    assert "1 from a.json" in out
    assert "1 from b.json" in out
    assert "= 2 total" in out


def test_main_is_idempotent_byte_for_byte(tmp_path):
    source_a = _write_source(tmp_path / "a.json", [
        {"sku": "A1", "outcome": "found", "search_raw_text": "1. x\n   y\n   z", "offer": {"price": "10.00"}},
    ])
    out_path = tmp_path / "extraction_gold.json"

    build_extraction_gold.main(["--sources", str(source_a), "--out", str(out_path)])
    first = out_path.read_bytes()
    build_extraction_gold.main(["--sources", str(source_a), "--out", str(out_path)])
    second = out_path.read_bytes()

    assert first == second
