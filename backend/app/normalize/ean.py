from __future__ import annotations


def is_valid_ean(code: str) -> bool:
    if not code.isdigit():
        return False

    if len(code) == 13:
        weights = [1, 3] * 6
        digits = [int(c) for c in code[:12]]
    elif len(code) == 8:
        weights = [3, 1, 3, 1, 3, 1, 3]
        digits = [int(c) for c in code[:7]]
    else:
        return False

    checksum = int(code[-1])
    total = sum(d * w for d, w in zip(digits, weights))
    calculated = (10 - (total % 10)) % 10
    return calculated == checksum


def normalize_ean(raw: str) -> tuple[str | None, str | None]:
    code = raw.strip()
    if not code:
        return None, None

    if len(code) == 12 and code.isdigit():
        # UPC-A is numerically identical to EAN-13 with a leading zero.
        code = "0" + code

    if is_valid_ean(code):
        return code, None

    return None, f"invalid EAN checksum '{code}', ean cleared"
