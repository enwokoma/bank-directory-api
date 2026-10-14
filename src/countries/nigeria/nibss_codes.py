"""Attach NIBSS institution codes to the CBN register's banks.

The CBN register and the NIP institution list spell names differently
("Citibank Nigeria Limited" and "CITI BANK"), and a wrong code would send
transfers to the wrong institution, so matching is conservative:

1. A reviewed entry in `nibss_code_matches.json` always wins. It maps a name
   exactly as the CBN publishes it to a code, or to null for a bank that must
   stay without one.
2. Otherwise a bank gets a code only when its normalized name matches exactly
   one NIP institution of a plausible type (the code falls in a range NIBSS
   uses for that type, and the name's type words agree), and no other bank
   claims that institution.

Everything else stays without a code and is listed in the refresh report.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.countries.nigeria.nip import NipInstitution

MATCHES_FILE = Path(__file__).with_name("nibss_code_matches.json")
SCHEME = "nibss_code"

# Leading digits of the NIBSS codes each type of institution holds, from the
# NIP list itself: deposit money banks are 000xxx, microfinance banks 090xxx, and so on.
CODE_PREFIXES = {
    "commercial": ("000",),
    "merchant": ("000", "060", "400"),
    "non_interest": ("000", "090"),
    "payment_service": ("120",),
    "microfinance": ("050", "070", "090"),
    "mortgage": ("070", "090", "100"),
    "mobile_money": ("100",),
}

# Words in an NIP name that say what kind of institution it is.
_TYPE_WORDS = {
    "microfinance": r"micro-?\s?finance|\bmfb\b",
    "mortgage": r"mortgage|savings (?:and|&) loans|\bhomes\b",
    "merchant": r"\bmerchant\b",
    "payment_service": r"payment service|\bpsb\b",
}

_FILLER_WORDS = frozenset(
    "micro finance microfinance mfb mf bank banks plc limited ltd nigeria nig of the and company co "
    "mortgage psb payment service services digital technologies technology".split()
)


@dataclass
class MatchReport:
    automatic: int = 0
    reviewed: int = 0
    unmatched_banks: list[str] = field(default_factory=list)
    unused_institutions: list[NipInstitution] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    # (bank name, code, NIP name, "automatic" or "reviewed") for every match made.
    matches: list[tuple[str, str, str, str]] = field(default_factory=list)


def load_reviewed_matches(path: Path = MATCHES_FILE) -> dict[str, str | None]:
    """Read the reviewed name -> code (or null) matches."""
    matches = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(matches, dict):
        raise ValueError(f"{path.name} must contain a JSON object.")
    return matches


def _plausible(bank: dict[str, Any], institution: NipInstitution) -> bool:
    """Reject automatic matches whose code range or type words disagree with the bank's type."""
    if not institution.code.startswith(CODE_PREFIXES.get(bank["type"], ())):
        return False
    hinted = {kind for kind, pattern in _TYPE_WORDS.items() if re.search(pattern, institution.name, re.IGNORECASE)}
    return not hinted or bank["type"] in hinted or bank["type"] == "non_interest"


def match_key(name: str) -> str:
    """Reduce a name to its distinctive words, run together, so both lists' spellings compare equal.

    Spaces are dropped because the lists split names differently: "COAL CAMP MFB" and
    "CoalCamp Microfinance Bank" are the same bank.
    """
    text = html.unescape(name).lower().replace("&", " ")
    text = re.sub(r"\((?:formerly|former)\b[^)]*\)", " ", text)
    text = re.sub(r"micro-finance", "microfinance", text)
    words = [word for word in re.findall(r"[a-z0-9]+", text) if word not in _FILLER_WORDS]
    return "".join(words)


def assign_nibss_codes(
    banks: list[dict[str, Any]],
    institutions: list[NipInstitution],
    reviewed: dict[str, str | None],
) -> MatchReport:
    """Set `identifiers.nibss_code` on the banks that can be matched, and report the rest."""
    report = MatchReport()
    by_code = {institution.code: institution for institution in institutions}
    by_key: dict[str, list[NipInstitution]] = {}
    for institution in institutions:
        by_key.setdefault(match_key(institution.name), []).append(institution)

    bank_names = {bank["name"] for bank in banks}
    for name in sorted(set(reviewed) - bank_names):
        report.problems.append(f"Reviewed match for {name!r} names no bank in the register.")

    reviewed_codes = {code for code in reviewed.values() if code}
    claims: dict[str, list[dict[str, Any]]] = {}
    for bank in banks:
        if bank["name"] in reviewed:
            continue
        key = match_key(bank["name"])
        candidates = [institution for institution in by_key.get(key, []) if key and _plausible(bank, institution)]
        if len(candidates) == 1 and candidates[0].code not in reviewed_codes:
            claims.setdefault(candidates[0].code, []).append(bank)

    used: set[str] = set()
    for bank in banks:
        code: str | None
        if bank["name"] in reviewed:
            code = reviewed[bank["name"]]
            if code is not None and code not in by_code:
                report.problems.append(f"Reviewed code {code} for {bank['name']!r} is not in the NIP list.")
                code = None
            if code is not None:
                report.reviewed += 1
        else:
            code = next((code for code, holders in claims.items() if holders == [bank]), None)
            if code is not None:
                report.automatic += 1
        bank["identifiers"].pop(SCHEME, None)
        if code is None:
            report.unmatched_banks.append(bank["name"])
            continue
        if code in used:
            report.problems.append(f"Code {code} would be given to more than one bank; {bank['name']!r} left without it.")
            report.unmatched_banks.append(bank["name"])
            continue
        used.add(code)
        bank["identifiers"][SCHEME] = code
        how = "reviewed" if bank["name"] in reviewed else "automatic"
        report.matches.append((bank["name"], code, by_code[code].name, how))

    in_scope = tuple({prefix for prefixes in CODE_PREFIXES.values() for prefix in prefixes})
    report.unused_institutions = [
        institution for institution in institutions if institution.code not in used and institution.code.startswith(in_scope)
    ]
    return report
