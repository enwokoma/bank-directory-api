"""Rebuild Nigeria's bank list from the Central Bank of Nigeria's register.

The CBN website's Financial Institutions pages load their tables from a small
JSON API with one list endpoint per licence category. This module reads those
lists and returns records in the shared dataset shape.

The site also has a per-institution detail endpoint with licence tier and
website, but it answers HTTP 500 for many institutions and its websites are
out of date, so it is not used.

Run it through the refresh command: `python -m src.refresh NGA`.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.cleaning import clean_text
from src.core.source_client import SourceClient

logger = logging.getLogger(__name__)

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


def fetch_dataset(client: SourceClient) -> dict[str, Any]:
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
    return {"sources": [SOURCE], "banks": drop_duplicate_names(list(banks.values()))}


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
