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
                          "offer": {"price": "5.00", "price_flag": None}}
    found_suspicious = {"sku": "C", "outcome": "found", "search_raw_text": "1. x\n   y\n   z",
                         "offer": {"price": "0.01", "price_flag": "suspiciously_low"}}
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


def test_build_gold_entries_merges_across_sources_and_counts_per_file(tmp_path):
    source_a = _write_source(tmp_path / "a.json", [
        {"sku": "A1", "outcome": "found", "search_raw_text": "1. x\n   y\n   z", "offer": {"price": "10.00"}},
        {"sku": "A2", "outcome": "not_found", "search_raw_text": None},
        {"sku": "A3", "outcome": "found", "search_raw_text": "1. x\n   y\n   z",
         "offer": {"price": "1.00", "price_flag": "suspiciously_low"}},
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
         "offer": {"price": "0.50", "price_flag": "suspiciously_low"}},
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
