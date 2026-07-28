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
        return "utf-8"
    except UnicodeDecodeError:
        return "cp1250"


def detect_dialect(sample_text: str) -> type[csv.Dialect]:
    try:
        return csv.Sniffer().sniff(sample_text, delimiters=";,")
    except csv.Error:
        return _DefaultDialect
