"""Which bank an account number belongs to, from the number alone.

A Nigerian account number does not name its bank, but its check digit was
computed from the issuing institution's code (see `nuban.py`), so the number
can be tested against every institution's code: an institution whose code
gives a different check digit cannot have issued it. That rules out about
nine in ten and leaves the rest, typically 30 to 50 of the 400 or so
institutions that can receive transfers. The survivors are ranked by how
likely each is to hold the account:

- A prior for each institution: how often transfers go to it. Reviewed
  estimates for the well-known ones and a default per bank type, kept in
  `account_detection.json`.
- Phone-number accounts. OPay, PalmPay, Moniepoint, Paga and the payment
  service banks give customers their mobile number as account number, which
  does not follow NUBAN. The check digit never rules those institutions out,
  and a number shaped like a Nigerian mobile number counts for them: mobile
  numbers are a 5% slice of all 10-digit numbers, so an institution whose
  accounts are mobile numbers is far denser there than one whose serial
  numbers spread across the whole range.
- Leading digits. Some banks' account numbers start with known digits
  (Guaranty Trust Bank's all start with 0). Listed per bank in the same file
  and applied softly, since the lists are observations rather than rules.
- A hint. Text copied along with the number often names the bank ("GTBank
  0123456789 John Doe"); an institution the hint names outranks everything.

Each candidate's confidence is its share of the total, an estimate of the
probability that it is the right institution; candidates whose share rounds
to nothing are left out. The check digit carries one digit of information, so
the list is for trying candidates in order against a name enquiry, not for
picking a bank without one.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from src.core.dataset import CountryDataset, search_text
from src.core.detection import Candidate, Detection
from src.countries.nigeria import nuban
from src.countries.nigeria.cbn_bank_codes import SCHEME as CBN_BANK_CODE
from src.countries.nigeria.profile import NIGERIA_PROFILE

SETTINGS_FILE = Path(__file__).with_name("account_detection.json")

# How likely the number is for each kind of institution, relative to 1 for a
# NUBAN-issuing institution whose code gives the number's check digit. One
# whose code gives another digit cannot have issued it (0).
#
# An institution that also hands out account numbers outside NUBAN, such as
# phone numbers, is not ruled out by a failed check: the digit says nothing
# about such numbers, and one in ten passes by chance.
CHECK_DIGIT_UNSURE = 0.1
# Mobile numbers are 5% of all 10-digit numbers (those starting 70, 80, 81, 90
# or 91), so an institution whose accounts are mobile numbers is 20 times
# denser on them than one whose serial numbers spread over the whole range; a
# tenth of that, since a NUBAN institution's check digit is fixed while a mobile
# number's last digit is free.
MOBILE_NUMBER_DENSITY = 2.0
# Leading digits a bank is known to use, applied softly: the lists are observations.
PREFIX_MATCH = 2.0
PREFIX_MISMATCH = 0.3
# A hint naming the institution is decisive: the factor is large enough that
# the smallest institution the hint names outranks the most common one with
# every other kind of evidence, and it keeps the named institution in the list
# even when the check digit rules it out.
HINT_MATCH = 100_000.0
HINT_FLOOR = 0.1

# The evidence a candidate can carry, strongest first.
REASONS = ("hint", "phone_number_account", "check_digit", "account_prefix")

_FORMER_NAME = re.compile(r"\((?:formerly|former)\b[^)]*\)", re.IGNORECASE)
_NAME_SUFFIXES = frozenset({"plc", "limited", "ltd", "nigeria", "nig", "co", "company"})
_INSTITUTION_KEYS = {"share", "phone_number_accounts", "account_prefixes", "aliases"}


@dataclass(frozen=True)
class InstitutionSettings:
    """Reviewed knowledge about one institution, from `account_detection.json`."""

    # How often transfers go to it, on any scale; None for its bank type's default.
    share: float | None = None
    # The fraction of its accounts whose number is the customer's mobile number.
    phone_number_accounts: float = 0.0
    # Leading digits its account numbers are known to start with.
    account_prefixes: tuple[str, ...] = ()
    # Short names people call it, normalized like a hint.
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class DetectionSettings:
    # Bank type code -> share of transfers for an institution of that type not listed below.
    default_shares: dict[str, float]
    # Bank id -> what is known about it.
    institutions: dict[str, InstitutionSettings]


_UNLISTED = InstitutionSettings()


def load_settings(path: Path = SETTINGS_FILE) -> DetectionSettings:
    """Read and check the reviewed settings file."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    try:
        default_shares = {bank_type: _share(share) for bank_type, share in raw["default_share_by_type"].items()}
        institutions = {bank_id: _institution_settings(item) for bank_id, item in raw["institutions"].items()}
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{path.name} is not valid: {exc}") from exc
    missing = set(NIGERIA_PROFILE.bank_type_codes()) - set(default_shares)
    if missing:
        raise ValueError(f"{path.name} has no default share for bank types {sorted(missing)}.")
    return DetectionSettings(default_shares=default_shares, institutions=institutions)


@cache
def default_settings() -> DetectionSettings:
    return load_settings()


def detect(
    dataset: CountryDataset,
    account_number: str,
    *,
    hint: str | None = None,
    types: Collection[str] | None = None,
    settings: DetectionSettings | None = None,
) -> Detection:
    """Rank the institutions that may hold the account; see the module docstring.

    Only active institutions with a NIBSS code are considered, since the point
    is to send a transfer; `types` narrows them to those bank types. Raises
    ValueError for an account number it cannot read.
    """
    settings = settings or default_settings()
    number = nuban.parse_account_number(account_number)
    mobile = nuban.looks_like_mobile_number(number)
    hint_words = _hint_words(hint)

    scored: list[tuple[float, dict[str, Any], tuple[str, ...], str, bool]] = []
    for bank in dataset.banks:
        if bank["status"] != "active" or "nibss_code" not in bank["identifiers"]:
            continue
        if types and bank["type"] not in types:
            continue
        institution = settings.institutions.get(bank["id"], _UNLISTED)
        code = institution_code(bank)
        valid = nuban.is_valid(number, code)
        hinted = bool(hint_words) and _named_in(hint_words, bank, institution.aliases)
        likelihood, reasons = _likelihood(number, mobile, valid, hinted, institution)
        if likelihood <= 0:
            continue
        share = institution.share if institution.share is not None else settings.default_shares[bank["type"]]
        scored.append((share * likelihood, bank, reasons, code, valid))

    total = sum(score for score, *_ in scored)
    scored.sort(key=lambda item: (-item[0], item[1]["name"]))
    # An institution whose confidence rounds to nothing, as every other one does
    # once a hint names one, is not worth listing.
    candidates = tuple(
        Candidate(
            bank=bank,
            confidence=confidence,
            reasons=reasons,
            institution_code=code,
            check_digit_valid=valid,
        )
        for score, bank, reasons, code, valid in scored
        if (confidence := round(score / total, 4)) > 0
    )
    return Detection(account_number=number, looks_like_phone_number=mobile, candidates=candidates)


def institution_code(bank: dict[str, Any]) -> str:
    """The 6-digit code to test the check digit with: from the CBN bank code, or else the NIBSS code as it is."""
    cbn_code = bank["identifiers"].get(CBN_BANK_CODE)
    return nuban.institution_code(cbn_code) if cbn_code else bank["identifiers"]["nibss_code"]


def normalize_name(text: str) -> str:
    """Lowercase words separated by single spaces, without accents or punctuation, so names and hints compare equal."""
    return " ".join(re.findall(r"[a-z0-9]+", search_text(text)))


def short_name(name: str) -> str:
    """The name as people write it: without a "(formerly ...)" note or a trailing Plc, Limited or Nigeria."""
    words = normalize_name(_FORMER_NAME.sub(" ", name)).split()
    while len(words) > 1 and words[-1] in _NAME_SUFFIXES:
        words.pop()
    return " ".join(words)


def _likelihood(
    number: str, mobile: bool, valid: bool, hinted: bool, institution: InstitutionSettings
) -> tuple[float, tuple[str, ...]]:
    reasons = set()
    phone_share = institution.phone_number_accounts
    if valid:
        nuban_part = 1.0
        reasons.add("check_digit")
    else:
        nuban_part = CHECK_DIGIT_UNSURE if phone_share else 0.0
    if nuban_part and institution.account_prefixes:
        if number.startswith(institution.account_prefixes):
            nuban_part *= PREFIX_MATCH
            reasons.add("account_prefix")
        else:
            nuban_part *= PREFIX_MISMATCH
    likelihood = (1 - phone_share) * nuban_part
    if phone_share and mobile:
        likelihood += phone_share * MOBILE_NUMBER_DENSITY
        reasons.add("phone_number_account")
    if hinted:
        likelihood = max(likelihood, HINT_FLOOR) * HINT_MATCH
        reasons.add("hint")
    return likelihood, tuple(reason for reason in REASONS if reason in reasons)


def _hint_words(hint: str | None) -> str:
    """The hint as " word word ", so that a name matches only at word boundaries."""
    words = normalize_name(hint or "")
    return f" {words} " if words else ""


def _named_in(hint_words: str, bank: dict[str, Any], aliases: tuple[str, ...]) -> bool:
    names = {short_name(bank["name"]), short_name(bank["trading_name"]), *aliases}
    return any(f" {name} " in hint_words for name in names if name)


def _share(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"a share must be a positive number, not {value!r}")
    return float(value)


def _institution_settings(item: Any) -> InstitutionSettings:
    if not isinstance(item, dict):
        raise ValueError("each institution must be an object")
    unknown = set(item) - _INSTITUTION_KEYS
    if unknown:
        raise ValueError(f"unknown keys {sorted(unknown)}")
    phone_share = item.get("phone_number_accounts", 0)
    if isinstance(phone_share, bool) or not isinstance(phone_share, (int, float)) or not 0 <= phone_share <= 1:
        raise ValueError(f"phone_number_accounts must be a fraction from 0 to 1, not {phone_share!r}")
    prefixes = tuple(item.get("account_prefixes", ()))
    if not all(isinstance(prefix, str) and prefix.isdigit() for prefix in prefixes):
        raise ValueError(f"account_prefixes must be strings of digits, not {prefixes!r}")
    aliases = tuple(normalize_name(alias) for alias in item.get("aliases", ()))
    if not all(aliases):
        raise ValueError("aliases must be non-empty text")
    return InstitutionSettings(
        share=_share(item["share"]) if "share" in item else None,
        phone_number_accounts=float(phone_share),
        account_prefixes=prefixes,
        aliases=aliases,
    )
