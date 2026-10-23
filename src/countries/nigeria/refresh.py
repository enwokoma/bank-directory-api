"""Rebuild Nigeria's bank list from the Central Bank of Nigeria's register.

The CBN website's Financial Institutions pages load their tables from a small
JSON API with one list endpoint per licence category. This module reads those
lists, adds the mobile money operators from the CBN's payments pages, and
returns records in the shared dataset shape.

The site also has a per-institution detail endpoint with licence tier and
website, but it answers HTTP 500 for many institutions and its websites are
out of date, so it is not used.

Run it through the refresh command: `python -m src.refresh NGA`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.core.cleaning import clean_text
from src.core.source_client import SourceClient
from src.core.trading_names import apply_trading_names, load_trading_names
from src.countries.nigeria import cbn_bank_codes, mobile_money, nibss_codes, nip

logger = logging.getLogger(__name__)

# Reviewed names banks trade under where the register still has an older one.
TRADING_NAMES_FILE = Path(__file__).with_name("trading_names.json")

CBN_BASE_URL = "https://www.cbn.gov.ng"
SOURCE = {
    "name": "Central Bank of Nigeria: Financial Institutions",
    "url": "https://www.cbn.gov.ng/supervision/finstitutions.html",
}

# Listed in the order the CBN site lists them. If an institution ever appears
# in two lists, the first category wins.
CATEGORY_ENDPOINTS = (
    ("commercial", "/api/GetDMBs"),
    ("merchant", "/api/GetMBs"),
    ("non_interest", "/api/GetNIBs"),
    ("payment_service", "/api/GetPSBs"),
    ("microfinance", "/api/GetMFBs"),
    ("mortgage", "/api/GetPMIs"),
)


def fetch_dataset(client: SourceClient, previous_banks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return Nigeria's sources and bank records, without ids, from the live CBN API."""
    banks: dict[str, dict[str, Any]] = {}
    for bank_type, endpoint in CATEGORY_ENDPOINTS:
        rows = client.get_json(CBN_BASE_URL + endpoint, params={"format": "json"})
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"CBN returned no institutions for {bank_type} ({endpoint}).")
        logger.info("CBN lists %d %s institutions", len(rows), bank_type)
        for row in rows:
            bank = build_bank(bank_type, row)
            institution_id = bank["identifiers"]["cbn_institution_id"]
            if institution_id in banks:
                logger.warning(
                    "CBN institution %s is listed as %s and %s", institution_id, banks[institution_id]["type"], bank_type
                )
                continue
            banks[institution_id] = bank
    operators = mobile_money.fetch_mobile_money_operators(client)
    logger.info("CBN lists %d mobile money operators", len(operators))
    records = drop_duplicate_names(list(banks.values())) + operators
    sources = [SOURCE, mobile_money.SOURCE]

    settings = nip.settings_from_env()
    if not settings:
        kept = keep_previous_nibss_codes(records, previous_banks or [])
        logger.warning("%s is not set, so the %d NIBSS codes already in the file were kept.", nip.ENV_URL, kept)
        cites_nip = kept > 0
    else:
        institutions = []
        for number, list_settings in enumerate(settings, start=1):
            listed = nip.fetch_nip_institutions(client, list_settings)
            logger.info("NIP institution list %d has %d institutions", number, len(listed))
            if not listed:
                logger.warning("%s carries no NIBSS codes, so it only serves the bank-code report.", list_settings.setting)
            institutions += listed
        report = nibss_codes.assign_nibss_codes(
            records, institutions, nibss_codes.load_reviewed_matches(nibss_codes.MATCHES_FILE)
        )
        log_match_report(report, records)
        cites_nip = True

    # The CBN bank codes come from a reviewed file rather than a fetch, so they
    # need no settings and are applied on every refresh.
    codes = cbn_bank_codes.load_cbn_bank_codes(cbn_bank_codes.CODES_FILE)
    for problem in cbn_bank_codes.apply_cbn_bank_codes(records, codes):
        logger.warning(problem)
    if any(cbn_bank_codes.SCHEME in record["identifiers"] for record in records):
        sources.extend(cbn_bank_codes.SOURCES)
    if cites_nip:
        sources.append(nip.SOURCE)

    for problem in apply_trading_names(records, load_trading_names(TRADING_NAMES_FILE)):
        logger.warning(problem)
    return {"sources": sources, "banks": records}


def keep_previous_nibss_codes(records: list[dict[str, Any]], previous_banks: list[dict[str, Any]]) -> int:
    """Copy each bank's NIBSS code from the previous file, matched by CBN record id or else by name."""
    by_cbn_id: dict[str, str] = {}
    by_name: dict[str, str] = {}
    for bank in previous_banks:
        code = bank.get("identifiers", {}).get(nibss_codes.SCHEME)
        if not code:
            continue
        cbn_id = bank["identifiers"].get("cbn_institution_id")
        if cbn_id:
            by_cbn_id[cbn_id] = code
        else:
            by_name[bank["name"]] = code
    kept = 0
    for record in records:
        cbn_id = record["identifiers"].get("cbn_institution_id")
        code = by_cbn_id.get(cbn_id) if cbn_id else by_name.get(record["name"])
        if code:
            record["identifiers"][nibss_codes.SCHEME] = code
            kept += 1
    return kept


def log_match_report(report: nibss_codes.MatchReport, records: list[dict[str, Any]]) -> None:
    """Print what still needs a reviewed match, so the matches file can be extended."""
    logger.info("NIBSS codes: %d matched automatically, %d from reviewed matches.", report.automatic, report.reviewed)
    for name, code, nip_name, how in report.matches:
        logger.debug("  matched (%s): %s -> %s %s", how, name, code, nip_name)
    for problem in report.problems:
        logger.warning(problem)
    types = {record["name"]: record["type"] for record in records}
    unmatched = [name for name in report.unmatched_banks if types[name] != "microfinance"]
    logger.info(
        "%d banks have no NIBSS code (%d microfinance banks, most of which are not on NIP).",
        len(report.unmatched_banks),
        len(report.unmatched_banks) - len(unmatched),
    )
    for name in unmatched:
        logger.info("  no code: %s (%s)", name, types[name])
    logger.info("%d NIP institutions of these types matched no bank:", len(report.unused_institutions))
    for institution in report.unused_institutions:
        logger.info("  unused: %s %s", institution.code, institution.name)


def drop_duplicate_names(banks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one record per name, the one with the lowest CBN id.

    The register has entered some microfinance banks twice under two record
    ids, with the same name, town and licence date. Company names are unique
    in Nigeria, so records that share a name are the same bank.
    """
    kept: dict[str, dict[str, Any]] = {}
    for bank in sorted(banks, key=lambda bank: int(bank["identifiers"]["cbn_institution_id"])):
        key = bank["name"].casefold()
        if key in kept:
            logger.warning(
                "CBN lists %s twice (ids %s and %s); keeping %s",
                bank["name"],
                kept[key]["identifiers"]["cbn_institution_id"],
                bank["identifiers"]["cbn_institution_id"],
                kept[key]["identifiers"]["cbn_institution_id"],
            )
            continue
        kept[key] = bank
    return list(kept.values())


def build_bank(bank_type: str, row: dict[str, Any]) -> dict[str, Any]:
    """Turn one row of a CBN category list into a dataset record."""
    institution_id = row.get("id")
    name = clean_text(row.get("name"))
    if institution_id is None or not name:
        raise ValueError(f"CBN {bank_type} row is missing an id or name: {row!r}")
    return {
        "name": name,
        "type": bank_type,
        "identifiers": {"cbn_institution_id": str(institution_id)},
    }
