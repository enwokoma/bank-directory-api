"""Tests for the NUBAN check digit arithmetic."""

import pytest

from src.countries.nigeria import nuban


def test_cbn_illustration_for_a_bank():
    """The revised standard's illustration 1: bank code 011 becomes 000011; serial 000001457 gives 81, check digit 9."""
    assert nuban.institution_code("011") == "000011"
    assert nuban.check_digit("000011", "000001457") == "9"
    assert nuban.make_account_number("000011", "000001457") == "0000014579"
    assert nuban.is_valid("0000014579", "000011")


def test_cbn_illustration_for_another_financial_institution():
    """Illustration 2: the 5-digit code 50547 becomes 950547; serial 000021457 gives 211, check digit 9."""
    assert nuban.institution_code("50547") == "950547"
    assert nuban.check_digit("950547", "000021457") == "9"
    assert nuban.make_account_number("950547", "000021457") == "0000214579"


def test_three_digit_code_gives_the_same_digit_as_the_2010_algorithm():
    """Guaranty Trust Bank (058) and serial 001656322 give 0016563228, as public implementations of the 2010 rules do."""
    assert nuban.make_account_number(nuban.institution_code("058"), "001656322") == "0016563228"


def test_check_digit_is_zero_when_the_sum_is_a_multiple_of_ten():
    assert nuban.check_digit("000011", "000000000") == "0"


@pytest.mark.parametrize(
    "code, expected",
    [("058", "000058"), ("50515", "950515"), ("100004", "100004"), (" 044 ", "000044")],
)
def test_institution_code_pads_cbn_codes_to_six_digits(code, expected):
    assert nuban.institution_code(code) == expected


@pytest.mark.parametrize("code", ["58", "0058", "5051", "5051555", "05A", ""])
def test_rejects_malformed_cbn_codes(code):
    with pytest.raises(ValueError, match="3, 5 or 6 digits"):
        nuban.institution_code(code)


def test_one_number_is_valid_for_several_institutions():
    """5050114930 passes for Providus (101), Standard Chartered (068), Wema (035) and Zenith (057), but not GTBank or Access."""
    passing = {
        code
        for code in ("101", "068", "035", "057", "058", "044")
        if nuban.is_valid("5050114930", nuban.institution_code(code))
    }
    assert passing == {"101", "068", "035", "057"}


def test_rejects_wrong_lengths():
    with pytest.raises(ValueError, match="6 digits"):
        nuban.check_digit("00011", "000001457")
    with pytest.raises(ValueError, match="9 digits"):
        nuban.check_digit("000011", "0001457")
    with pytest.raises(ValueError, match="10 digits"):
        nuban.is_valid("123", "000011")


@pytest.mark.parametrize(
    "value, expected",
    [
        ("0123456789", "0123456789"),
        (" 0123 456 789 ", "0123456789"),
        ("0123-456-789", "0123456789"),
        ("08012345678", "8012345678"),
        ("0801 234 5678", "8012345678"),
        ("+234 801 234 5678", "8012345678"),
        ("2348012345678", "8012345678"),
        ("(0)901-234-5678", "9012345678"),
    ],
)
def test_parses_account_numbers_and_mobile_numbers(value, expected):
    assert nuban.parse_account_number(value) == expected


@pytest.mark.parametrize(
    "value",
    ["012345678", "01234567890", "00123456789", "+234 012 345 6789", "0123a56789", "", "0123456789 ext 1"],
)
def test_refuses_other_lengths_and_characters(value):
    with pytest.raises(ValueError, match="account_number must"):
        nuban.parse_account_number(value)


@pytest.mark.parametrize(
    "number, mobile",
    [
        ("8012345678", True),
        ("7012345678", True),
        ("9123456789", True),
        ("8181234567", True),
        ("0123456789", False),
        ("6012345678", False),
        ("7912345678", False),
        ("1234567890", False),
    ],
)
def test_recognizes_nigerian_mobile_numbers(number, mobile):
    assert nuban.looks_like_mobile_number(number) is mobile
