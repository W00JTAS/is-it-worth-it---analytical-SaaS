from __future__ import annotations

import csv


class _DefaultDialect(csv.Dialect):
    delimiter = ";"
    quotechar = '"'
    doublequote = True
    skipinitialspace = False
    lineterminator = "\r\n"
    quoting = csv.QUOTE_MINIMAL


def detect_encoding(raw_bytes: bytes) -> str:
    try:
        raw_bytes.decode("utf-8")
        # "utf-8-sig" transparently strips a leading BOM (the default when
        # Excel on Windows exports CSV) while still decoding plain UTF-8
        # without a BOM identically -- handles both cases uniformly.
        return "utf-8-sig"
    except UnicodeDecodeError:
        return "cp1250"


def detect_dialect(sample_text: str) -> type[csv.Dialect]:
    try:
        dialect = csv.Sniffer().sniff(sample_text, delimiters=";,")
        # csv.Sniffer's doublequote heuristic is unreliable on real-world data:
        # it can guess False even when a quoted field legitimately contains an
        # RFC 4180 doubled-quote escape ("" for a literal "), which then causes
        # the csv module to misparse the row (fields shift silently). Virtually
        # all real-world quoted CSV exports use RFC 4180 escaping, so force it,
        # matching the assumption already made by _DefaultDialect below.
        dialect.doublequote = True
        return dialect
    except csv.Error:
        return _DefaultDialect
