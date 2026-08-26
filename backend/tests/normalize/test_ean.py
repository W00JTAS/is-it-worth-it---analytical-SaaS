from app.normalize.ean import is_valid_ean, normalize_ean


def test_valid_ean13_checksum():
    assert is_valid_ean("5901234123457") is True


def test_invalid_ean13_checksum():
    assert is_valid_ean("5901234123458") is False


def test_valid_ean8_checksum():
    assert is_valid_ean("40170725") is True


def test_invalid_ean8_checksum():
    assert is_valid_ean("40170724") is False


def test_non_digit_string_is_invalid():
    assert is_valid_ean("abcdefghijklm") is False


def test_wrong_length_is_invalid():
    assert is_valid_ean("123") is False


def test_normalize_ean_pads_upc_a_to_ean13():
    ean, warning = normalize_ean("698813001132")
    assert ean == "0698813001132"
    assert warning is None


def test_normalize_ean_returns_warning_on_bad_checksum():
    ean, warning = normalize_ean("5901234123458")
    assert ean is None
    assert warning == "invalid EAN checksum '5901234123458', ean cleared"


def test_normalize_ean_returns_none_for_blank_input():
    ean, warning = normalize_ean("")
    assert ean is None
    assert warning is None


def test_normalize_ean_strips_whitespace():
    ean, warning = normalize_ean("  5901234123457  ")
    assert ean == "5901234123457"
    assert warning is None


def test_normalize_ean_passes_through_valid_ean13_unchanged():
    ean, warning = normalize_ean("5901234123457")
    assert ean == "5901234123457"
    assert warning is None
