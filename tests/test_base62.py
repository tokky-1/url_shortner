import pytest

from core.codec import decode, encode


def test_round_trip():
    number = 123456789

    encoded = encode(number)

    assert decode(encoded) == number


def test_zero():
    assert encode(0) == "0"
    assert decode("0") == 0


def test_large_number():
    number = 10**18

    encoded = encode(number)

    assert decode(encoded) == number


def test_invalid_character():
    with pytest.raises(ValueError):
        decode("abc!")


# These three pin the alphabet and its order. If a library upgrade reorders
# ALPHABET, these fail instead of silently invalidating every issued link.
def test_last_single_digit_is_z():
    assert encode(61) == "z"


def test_first_two_digit_code_rolls_over_to_10():
    assert encode(62) == "10"


def test_digit_ten_is_uppercase_a():
    assert encode(10) == "A"


def test_negative_number_rejected():
    # base62.encode(-1) returns "0" without error, so every negative ID would
    # otherwise collide with ID 0.
    with pytest.raises(ValueError):
        encode(-1)


def test_empty_code_rejected():
    # base62.decode("") returns 0 without error, so a request for "/" would
    # otherwise resolve to ID 0.
    with pytest.raises(ValueError):
        decode("")


@pytest.mark.parametrize("number", [61, 62, 63])
def test_round_trip_at_alphabet_boundary(number):
    assert decode(encode(number)) == number
