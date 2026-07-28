from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_STRIP_PATTERN = re.compile(r"[^\d,.\-]")


class InvalidPriceError(Exception):
    pass


def parse_price(raw: str) -> Decimal:
    cleaned = _STRIP_PATTERN.sub("", raw.strip())
    if not cleaned:
        raise InvalidPriceError(raw)

    last_comma = cleaned.rfind(",")
    last_dot = cleaned.rfind(".")
    decimal_pos = max(last_comma, last_dot)

    if decimal_pos == -1:
        integer_part, decimal_part = cleaned, ""
    else:
        integer_part = cleaned[:decimal_pos]
        decimal_part = cleaned[decimal_pos + 1 :]

    integer_part = integer_part.replace(",", "").replace(".", "")

    if not integer_part.lstrip("-").isdigit() or (decimal_part and not decimal_part.isdigit()):
        raise InvalidPriceError(raw)

    normalized = f"{integer_part}.{decimal_part}" if decimal_part else integer_part

    try:
        value = Decimal(normalized)
    except InvalidOperation as exc:
        raise InvalidPriceError(raw) from exc

    if value < 0:
        raise InvalidPriceError(raw)

    return value
