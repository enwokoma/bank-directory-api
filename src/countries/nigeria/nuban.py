"""Nigeria Uniform Bank Account Number (NUBAN) arithmetic.

The Central Bank of Nigeria's NUBAN standard (August 2010, revised in 2019 to
cover other financial institutions) gives every account a 9-digit serial number
followed by a check digit computed from the serial number and the issuing
institution's code:

    institution code (6 digits) + serial number (9 digits) -> check digit

The 6-digit institution code is the CBN's 3-digit bank code with three leading
zeros for banks (Guaranty Trust Bank's 058 becomes 000058) and the CBN's
5-digit code with a leading 9 for other financial institutions (Moniepoint's
50515 becomes 950515). Each of the 15 digits is multiplied by 3, 7, 3, 3, 7, 3
and so on, the products are added up, and the check digit is 10 minus the sum
modulo 10, or 0 when that gives 10. The 2010 standard used the bare 3-digit
code with twelve weights; leading zeros add nothing, so both give the same
digit for the same bank.

Customers see only the serial number and the check digit, so a 10-digit
account number carries one digit of information about its bank: it is valid
for every institution whose code gives the same weighted sum modulo 10. The
check digit can rule a bank out, but never confirm one on its own.
"""

from __future__ import annotations

import re

WEIGHTS = (3, 7, 3) * 5
INSTITUTION_CODE_LENGTH = 6
SERIAL_LENGTH = 9
ACCOUNT_NUMBER_LENGTH = 10

# A Nigerian mobile number without its leading 0. The NCC allots mobile numbers
# in the 070x, 080x, 081x, 090x and 091x ranges, so a wallet account number made
# from one starts with 70, 80, 81, 90 or 91. The whole ranges are accepted, since
# new prefixes are allotted within them from time to time.
_MOBILE_NUMBER = re.compile(r"(?:70|80|81|90|91)[0-9]{8}")
_COUNTRY_CODE = "234"
_SEPARATORS = re.compile(r"[\s().+-]")


def institution_code(cbn_bank_code: str) -> str:
    """Return the 6-digit code the check digit is computed with.

    A 3-digit bank code gets three leading zeros, a 5-digit code of another
    financial institution gets a leading 9, and a 6-digit code is used as it is.
    """
    code = cbn_bank_code.strip()
    if not code.isdigit() or len(code) not in (3, 5, INSTITUTION_CODE_LENGTH):
        raise ValueError(f"A CBN bank code has 3, 5 or 6 digits, not {cbn_bank_code!r}.")
    if len(code) == 3:
        return "000" + code
    if len(code) == 5:
        return "9" + code
    return code


def check_digit(code: str, serial_number: str) -> str:
    """Compute the check digit of a 9-digit serial number issued under a 6-digit institution code."""
    digits = code + serial_number
    if len(code) != INSTITUTION_CODE_LENGTH or len(serial_number) != SERIAL_LENGTH or not digits.isdigit():
        raise ValueError("The institution code must be 6 digits and the serial number 9 digits.")
    total = sum(int(digit) * weight for digit, weight in zip(digits, WEIGHTS, strict=True))
    return str((10 - total % 10) % 10)


def make_account_number(code: str, serial_number: str) -> str:
    """Return the 10-digit account number: the serial number followed by its check digit."""
    return serial_number + check_digit(code, serial_number)


def is_valid(account_number: str, code: str) -> bool:
    """True when the account number's check digit is the one this institution code gives."""
    if len(account_number) != ACCOUNT_NUMBER_LENGTH or not account_number.isdigit():
        raise ValueError("An account number has 10 digits.")
    return check_digit(code, account_number[:SERIAL_LENGTH]) == account_number[SERIAL_LENGTH]


def looks_like_mobile_number(account_number: str) -> bool:
    """True when the 10 digits are a Nigerian mobile number without its leading 0, as wallet account numbers are."""
    return _MOBILE_NUMBER.fullmatch(account_number) is not None


def parse_account_number(value: str) -> str:
    """Return the 10 digits in `value`, which may carry spaces or dashes, or be a mobile number written in full.

    Wallet account numbers are the customer's mobile number without its leading
    0, so 0801 234 5678 and +234 801 234 5678 both give 8012345678. Any other
    length is refused rather than guessed at: a digit too many or too few is a typo.
    """
    digits = _SEPARATORS.sub("", value)
    if not digits.isdigit():
        raise ValueError("account_number must contain only digits, apart from spaces or dashes.")
    if len(digits) == 13 and digits.startswith(_COUNTRY_CODE) and looks_like_mobile_number(digits[3:]):
        return digits[3:]
    if len(digits) == 11 and digits.startswith("0") and looks_like_mobile_number(digits[1:]):
        return digits[1:]
    if len(digits) != ACCOUNT_NUMBER_LENGTH:
        raise ValueError(
            f"account_number must be 10 digits, not {len(digits)}; "
            "a wallet account can also be given as its mobile number, such as 08012345678."
        )
    return digits
