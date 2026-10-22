"""CBN bank codes: the codes NUBAN account numbers are generated with.

The Central Bank of Nigeria gives every bank a 3-digit code (058 for Guaranty
Trust Bank) and every other financial institution a 5-digit one (50515 for
Moniepoint). The NUBAN check digit is computed from it (see `nuban.py`), and
payment providers such as Paystack use it as the bank code in their transfer
APIs, but the CBN does not publish the list, and its register records only
its own row ids. So the codes are kept as a reviewed file,
`cbn_bank_codes.json`: a bank's name exactly as the CBN publishes it, mapped
to its code. The file was compiled from Paystack's bank list, which carries
both this code and the NIBSS code, and checked against published code lists
for the deposit money banks. Institutions whose code Paystack gives in another
form, such as OPay and PalmPay, are left out; detection then falls back to
their NIBSS code.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

CODES_FILE = Path(__file__).with_name("cbn_bank_codes.json")
SCHEME = "cbn_bank_code"
CODE_PATTERN = r"[0-9]{3}|[0-9]{5}"
SOURCE = {"name": "Paystack: bank list (CBN bank codes)", "url": "https://paystack.com/docs/api/miscellaneous/#bank"}


def load_cbn_bank_codes(path: Path = CODES_FILE) -> dict[str, str]:
    """Read the reviewed register name -> CBN bank code pairs."""
    codes = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(codes, dict) or not all(
        isinstance(code, str) and re.fullmatch(CODE_PATTERN, code) for code in codes.values()
    ):
        raise ValueError(f"{path.name} must map register names to 3- or 5-digit CBN bank codes.")
    return codes


def apply_cbn_bank_codes(records: list[dict[str, Any]], codes: dict[str, str]) -> list[str]:
    """Set `identifiers.cbn_bank_code` on every record the file names, and return any problems."""
    problems = []
    holders: dict[str, str] = {}
    for record in records:
        record["identifiers"].pop(SCHEME, None)
        code = codes.get(record["name"])
        if code is None:
            continue
        if code in holders:
            problems.append(
                f"CBN bank code {code} is given to both {holders[code]!r} and {record['name']!r}; "
                f"{record['name']!r} left without it."
            )
            continue
        holders[code] = record["name"]
        record["identifiers"][SCHEME] = code
    listed = {record["name"] for record in records}
    problems += [f"CBN bank code for {name!r} names no bank in the register." for name in sorted(set(codes) - listed)]
    return problems
