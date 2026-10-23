"""Payment providers' bank lists, for reviewing the CBN bank codes.

Payment providers publish the institutions their transfer APIs reach, each
with the bank code they take, which for most institutions is the CBN's (see
`cbn_bank_codes.py`), often with the NIBSS code next to it. Read side by side,
the lists show which institutions in the data file have a code the reviewed
file lacks, and where the lists disagree, so the reviewed file can be extended
by hand with open eyes. Nothing here changes a file: the command prints a
report.

    python -m src.countries.nigeria.bank_code_sources

Paystack's list is public. Monnify's needs MONNIFY_API_KEY and
MONNIFY_SECRET_KEY, and Flutterwave's FLUTTERWAVE_CLIENT_ID and
FLUTTERWAVE_CLIENT_SECRET, read from `.env` like the refresh's settings; a
provider without credentials, or one that cannot be reached, is skipped with
a note. Monnify's list carries legacy 3-digit NIBSS codes for some
institutions and the NIBSS code itself for many, so a code is reported with
the providers that give it, and a 6-digit code is never taken for a CBN one.
"""

from __future__ import annotations

import argparse
import base64
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
from src.countries.nigeria.cbn_bank_codes import SCHEME
from src.countries.nigeria.nibss_codes import match_key

ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
PAYSTACK_URL = "https://api.paystack.co/bank"
MONNIFY_LOGIN_URL = "https://api.monnify.com/api/v1/auth/login"
MONNIFY_BANKS_URL = "https://api.monnify.com/api/v1/banks"
FLUTTERWAVE_TOKEN_URL = "https://idp.flutterwave.com/realms/flutterwave/protocol/openid-connect/token"
FLUTTERWAVE_BANKS_URL = "https://api.flutterwave.cloud/f4bexperience/banks"

_CBN_CODE = re.compile(r"[0-9]{3}|[0-9]{5}")
_NIBSS_CODE = re.compile(r"[0-9]{6}")


@dataclass(frozen=True)
class ProviderCode:
    """One institution as a provider lists it."""

    provider: str
    name: str
    code: str
    # The NIBSS code the provider lists next to it, when it does.
    nibss_code: str | None = None


def fetch_paystack(client: SourceClient) -> list[ProviderCode]:
    """Paystack's list, which needs no key and carries the NIP code as nip_sort_code."""
    body = client.get_json(PAYSTACK_URL, params={"currency": "NGN", "include_nip_sort_code": "true", "perPage": "500"})
    return [
        ProviderCode("paystack", str(row.get("name") or ""), str(row.get("code") or ""), _nibss(row.get("nip_sort_code")))
        for row in _rows(body, "data")
    ]


def fetch_monnify(client: SourceClient, api_key: str, secret_key: str) -> list[ProviderCode]:
    """Monnify's list, after a login with the key pair, which carries the NIP code as nipBankCode."""
    basic = base64.b64encode(f"{api_key}:{secret_key}".encode()).decode()
    login = client.post_json(MONNIFY_LOGIN_URL, headers={"Authorization": f"Basic {basic}"})
    token = _dig(login, "responseBody", "accessToken")
    if not token:
        raise ValueError("Monnify's login answer has no access token.")
    body = client.get_json(MONNIFY_BANKS_URL, headers={"Authorization": f"Bearer {token}"})
    return [
        ProviderCode("monnify", str(row.get("name") or ""), str(row.get("code") or ""), _nibss(row.get("nipBankCode")))
        for row in _rows(body, "responseBody")
    ]


def fetch_flutterwave(client: SourceClient, client_id: str, client_secret: str) -> list[ProviderCode]:
    """Flutterwave's list, after an OAuth client-credentials login; it carries no NIP code, so names must match."""
    token_body = client.post_json(
        FLUTTERWAVE_TOKEN_URL,
        data={"client_id": client_id, "client_secret": client_secret, "grant_type": "client_credentials"},
    )
    token = token_body.get("access_token") if isinstance(token_body, dict) else None
    if not token:
        raise ValueError("Flutterwave's token answer has no access token.")
    body = client.get_json(FLUTTERWAVE_BANKS_URL, params={"country": "NG"}, headers={"Authorization": f"Bearer {token}"})
    return [ProviderCode("flutterwave", str(row.get("name") or ""), str(row.get("code") or "")) for row in _rows(body, "data")]


def collect(client: SourceClient, environ: Mapping[str, str] = os.environ) -> tuple[list[ProviderCode], list[str]]:
    """Fetch every provider's list that can be fetched, with a note for each one that cannot."""
    codes: list[ProviderCode] = []
    notes: list[str] = []
    monnify = (environ.get("MONNIFY_API_KEY") or "").strip(), (environ.get("MONNIFY_SECRET_KEY") or "").strip()
    flutterwave = (
        (environ.get("FLUTTERWAVE_CLIENT_ID") or "").strip(),
        (environ.get("FLUTTERWAVE_CLIENT_SECRET") or "").strip(),
    )
    providers: list[tuple[str, Any]] = [("Paystack", lambda: fetch_paystack(client))]
    if all(monnify):
        providers.append(("Monnify", lambda: fetch_monnify(client, *monnify)))
    else:
        notes.append("Monnify skipped: MONNIFY_API_KEY and MONNIFY_SECRET_KEY are not set.")
    if all(flutterwave):
        providers.append(("Flutterwave", lambda: fetch_flutterwave(client, *flutterwave)))
    else:
        notes.append("Flutterwave skipped: FLUTTERWAVE_CLIENT_ID and FLUTTERWAVE_CLIENT_SECRET are not set.")
    for name, fetch in providers:
        try:
            listed = fetch()
        except (SourceError, ValueError) as exc:
            notes.append(f"{name} skipped: {exc}")
            continue
        notes.append(f"{name} lists {len(listed)} institutions.")
        codes.extend(listed)
    return codes, notes


def report(banks: list[dict[str, Any]], codes: list[ProviderCode]) -> list[str]:
    """Describe what the providers' codes add to, or contradict in, the data file's CBN bank codes."""
    by_nibss = {bank["identifiers"]["nibss_code"]: bank for bank in banks if "nibss_code" in bank["identifiers"]}
    keyed: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for bank in banks:
        keyed[match_key(bank["name"])].append(bank)
    by_name = {key: found[0] for key, found in keyed.items() if len(found) == 1 and key}

    # Bank id -> {CBN-style code -> providers giving it}
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

    lines = [f"{len(missing)} institutions without a reviewed CBN bank code that a provider gives a code:"]
    lines += missing or ["  (none)"]
    lines.append(f"{len(disagreeing)} reviewed codes a provider disagrees with (3-digit codes are often legacy NIBSS codes):")
    lines += disagreeing or ["  (none)"]
    lines.append(f"{confirmed} reviewed codes every provider that lists the bank confirms.")
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


def _rows(body: Any, key: str) -> list[dict[str, Any]]:
    rows = body.get(key) if isinstance(body, dict) else body
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _dig(body: Any, *keys: str) -> Any:
    for key in keys:
        body = body.get(key) if isinstance(body, dict) else None
    return body


def _nibss(value: Any) -> str | None:
    code = str(value or "").strip()
    return code if _NIBSS_CODE.fullmatch(code) else None


def _cbn_style(value: str) -> str | None:
    """A 3- or 5-digit code, with leading zeros dropped from a padded 3-digit one; None for anything else."""
    digits = re.sub(r"[^0-9]", "", value)
    if len(digits) in (4, 5) and digits.startswith("0") and len(digits.lstrip("0")) == 3:
        digits = digits.lstrip("0")
    return digits if _CBN_CODE.fullmatch(digits) else None


if __name__ == "__main__":
    sys.exit(main())
