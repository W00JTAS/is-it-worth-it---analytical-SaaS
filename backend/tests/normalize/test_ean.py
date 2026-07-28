from app.normalize.ean import is_valid_ean


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
