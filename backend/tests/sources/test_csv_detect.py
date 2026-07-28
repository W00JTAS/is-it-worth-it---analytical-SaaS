import csv

from app.sources.csv_detect import detect_dialect, detect_encoding

SAMPLE_TEXT = "Nazwa;Cena;EAN;Kategoria\nŁóżko;100,00;5901234123457;Meble\n"


def test_detects_utf8_encoding():
    assert detect_encoding(SAMPLE_TEXT.encode("utf-8")) == "utf-8"


def test_falls_back_to_cp1250_when_utf8_decode_fails():
    assert detect_encoding(SAMPLE_TEXT.encode("cp1250")) == "cp1250"


def test_detects_semicolon_delimiter():
    dialect = detect_dialect(SAMPLE_TEXT)
    assert dialect.delimiter == ";"


def test_detects_comma_delimiter():
    comma_text = "Nazwa,Cena,EAN,Kategoria\nŁóżko,100.00,5901234123457,Meble\n"
    dialect = detect_dialect(comma_text)
    assert dialect.delimiter == ","


def test_falls_back_to_semicolon_when_sniffing_fails():
    dialect = detect_dialect("no delimiter characters at all")
    assert dialect.delimiter == ";"
