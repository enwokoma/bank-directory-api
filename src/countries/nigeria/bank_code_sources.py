"""Payment providers' bank lists, for reviewing the CBN bank codes.

Payment providers publish the institutions their transfer APIs reach, each
with the bank code they take, which for most institutions is the CBN's (see
`cbn_bank_codes.py`), often with the NIBSS code next to it. Read side by side,
the lists show which institutions in the data file have a code the reviewed
file lacks, and where the lists disagree, so the reviewed file can be extended
by hand with open eyes. Nothing here changes a file: the command prints a
report.

    python -m src.countries.nigeria.bank_code_sources

The lists are the institution lists the refresh reads, set in `.env` as
`NIP_INSTITUTIONS_URL`, `_2` to `_5`, with their keys and, for an endpoint
that needs a login first, `NIP_INSTITUTIONS_LOGIN_URL_n` (see `nip.py` and
`.env.example`): Paystack's list is public, Monnify's needs its key pair and
a login, Flutterwave's its secret key. A list that cannot be read is skipped
with a note. Some lists give legacy 3-digit NIBSS codes for a few
institutions and the NIBSS code itself for many, so a code is reported with
the lists that give it, and a 6-digit code is never taken for a CBN one.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.core.dataset import DATA_DIR
from src.core.source_client import SourceClient, SourceError
from src.countries.nigeria import nip
from src.countries.nigeria.cbn_bank_codes import SCHEME
from src.countries.nigeria.nibss_codes import match_key

ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

_CBN_CODE = re.compile(r"[0-9]{3}|[0-9]{5}")


@dataclass(frozen=True)
class ProviderCode:
    """One institution as a list gives it."""

    # The list it came from, as "list 1" to "list 5".
    provider: str
    name: str
    code: str
    # The NIBSS code the list gives next to it, when it does.
    nibss_code: str | None = None


def collect(client: SourceClient, environ: Mapping[str, str] = os.environ) -> tuple[list[ProviderCode], list[str]]:
    """Read every configured list that can be read, with a note for each one, read or not."""
    codes: list[ProviderCode] = []
    notes: list[str] = []
    settings = nip.settings_from_env(environ)
    if not settings:
        notes.append(f"No institution list is set: see {nip.ENV_URL} in .env.example.")
    for listing in settings:
        try:
            rows = nip.fetch_institution_list(client, listing)
        except (SourceError, ValueError) as exc:
            notes.append(f"{listing.label} skipped: {exc}")
            continue
        notes.append(f"{listing.label} ({listing.setting}) names {len(rows)} institutions.")
        codes += [ProviderCode(listing.label, row.name, row.code, row.nibss_code) for row in rows]
    return codes, notes


def report(banks: list[dict[str, Any]], codes: list[ProviderCode]) -> list[str]:
    """Describe what the lists' codes add to, or contradict in, the data file's CBN bank codes."""
    by_nibss = {bank["identifiers"]["nibss_code"]: bank for bank in banks if "nibss_code" in bank["identifiers"]}
    keyed: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for bank in banks:
        keyed[match_key(bank["name"])].append(bank)
    by_name = {key: found[0] for key, found in keyed.items() if len(found) == 1 and key}

    # Bank id -> {CBN-style code -> lists giving it}
    given: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for item in codes:
        listed = by_nibss.get(item.nibss_code or "") or by_name.get(match_key(item.name))
        code = _cbn_style(item.code)
        if listed is None or code is None or code == item.nibss_code:
            continue
        given[listed["id"]][code].add(item.provider)

    missing, disagreeing, confirmed = [], [], 0
    for bank in banks:
        offered = given.get(bank["id"])
        if not offered:
            continue
        reviewed = bank["identifiers"].get(SCHEME)
        offers = ", ".join(f"{code} ({', '.join(sorted(providers))})" for code, providers in sorted(offered.items()))
        if reviewed is None:
            missing.append(f"  {bank['identifiers'].get('nibss_code', '-'):6} {bank['name']}: {offers}")
        elif reviewed in offered and len(offered) == 1:
            confirmed += 1
        else:
            disagreeing.append(
                f"  {bank['identifiers'].get('nibss_code', '-'):6} {bank['name']}: reviewed {reviewed}; {offers}"
            )

    lines = [f"{len(missing)} institutions without a reviewed CBN bank code that a list gives a code:"]
    lines += missing or ["  (none)"]
    lines.append(f"{len(disagreeing)} reviewed codes a list disagrees with (3-digit codes are often legacy NIBSS codes):")
    lines += disagreeing or ["  (none)"]
    lines.append(f"{confirmed} reviewed codes every list that names the bank confirms.")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help="Folder that holds the country data files")
    args = parser.parse_args(argv)
    load_dotenv(ENV_FILE)
    banks = json.loads((args.data_dir / "NGA.json").read_text(encoding="utf-8"))["banks"]
    with SourceClient() as client:
        codes, notes = collect(client)
    for line in [*notes, *report(banks, codes)]:
        print(line)
    return 0


def _cbn_style(value: str) -> str | None:
    """A 3- or 5-digit code, with leading zeros dropped from a padded 3-digit one; None for anything else."""
    digits = re.sub(r"[^0-9]", "", value)
    if len(digits) in (4, 5) and digits.startswith("0") and len(digits.lstrip("0")) == 3:
        digits = digits.lstrip("0")
    return digits if _CBN_CODE.fullmatch(digits) else None


if __name__ == "__main__":
    sys.exit(main())
