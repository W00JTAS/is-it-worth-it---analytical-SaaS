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


def test_dialect_correctly_handles_doubled_quote_escaping():
    # Based on the real supplier row at backend/tests/fixtures/real_catalog.csv:3083,
    # which contains an RFC 4180 doubled-quote escape (3.5"") inside a quoted field,
    # plus a literal delimiter (;) inside that same quoted field. csv.Sniffer's
    # heuristic guesses doublequote=False on samples like this, which causes the
    # csv module to close the field early at the first embedded quote and then
    # re-split the remainder of the row on the delimiter -- silently shifting
    # every subsequent column (e.g. the price field gets replaced by a fragment
    # like "7200" from "7200 obr/min", which still parses as a "valid" price).
    sample = (
        '"ST4000NE001";"8719706009881";'
        '"Dysk HDD Seagate IronWolf Pro ST4000NE001 (4 TB ; 3.5""; 256 MB; 7200 obr/min)";'
        '"Dyski i akcesoria / Dyski HDD";"1133.42"\n'
        '"OTHER001";"1234567890123";"Other Widget";"Other Category";"99.99"\n'
    )

    dialect = detect_dialect(sample)
    assert dialect.doublequote is True

    rows = list(csv.reader(sample.splitlines(), dialect=dialect))
    first_row = rows[0]
    assert len(first_row) == 5
    assert first_row[-1] == "1133.42"
    assert (
        first_row[2]
        == 'Dysk HDD Seagate IronWolf Pro ST4000NE001 (4 TB ; 3.5"; 256 MB; 7200 obr/min)'
    )
