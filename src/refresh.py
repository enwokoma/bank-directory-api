"""Rebuild one country's data file from its official source.

Usage:

    python -m src.refresh NGA

The command asks the country's refresh module for fresh records, keeps the id
of every bank that was already in the file (matched by the profile's first
identifier scheme), validates the result, and only then overwrites
`data/countries/<ALPHA3>.json`. Review the diff before committing it.
"""

from __future__ import annotations

import argparse
import datetime
import importlib
import json
import logging
import sys
from pathlib import Path
from typing import Any

from src.core.cleaning import slugify
from src.core.dataset import DATA_DIR, bank_sort_key, validate_dataset
from src.core.source_client import SourceClient, SourceError
from src.countries.profile import CountryProfile
from src.countries.registry import get_country_profile

logger = logging.getLogger("refresh")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("country", help="ISO 3166-1 alpha-2 or alpha-3 code, for example NG or NGA")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help="Folder that holds the country data files")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    profile = get_country_profile(args.country)
    if profile is None:
        parser.error(f"No registered country for {args.country!r}.")
    path = args.data_dir / f"{profile.alpha3}.json"
    previous = _read_previous(path)

    module = importlib.import_module(profile.refresh_module)
    try:
        with SourceClient() as client:
            fetched = module.fetch_dataset(client)
    except (SourceError, ValueError) as exc:
        logger.error("Refresh failed, %s was not changed: %s", path.name, exc)
        return 1

    dataset = build_dataset(profile, fetched, previous.get("banks", []), datetime.date.today())
    errors = validate_dataset(dataset, profile)
    if errors:
        logger.error("Refreshed %s data is invalid, %s was not changed:\n- %s", profile.name, path.name, "\n- ".join(errors))
        return 1

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dataset, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    logger.info("Wrote %d banks to %s", len(dataset["banks"]), path)
    for line in summarize_changes(previous.get("banks", []), dataset["banks"]):
        logger.info(line)
    return 0


def build_dataset(
    profile: CountryProfile,
    fetched: dict[str, Any],
    previous_banks: list[dict[str, Any]],
    retrieved_on: datetime.date,
) -> dict[str, Any]:
    """Assemble a data file from fetched records, keeping existing ids stable."""
    banks = assign_ids(fetched["banks"], previous_banks, next(iter(profile.identifier_schemes)))
    return {
        "country": profile.alpha3,
        "retrieved_on": retrieved_on.isoformat(),
        "sources": fetched["sources"],
        "banks": sorted(banks, key=bank_sort_key),
    }


def assign_ids(records: list[dict[str, Any]], previous_banks: list[dict[str, Any]], key_scheme: str) -> list[dict[str, Any]]:
    """Give each record an id: its previous id when the bank was already listed, else a new slug.

    Reused ids are claimed first so a newly licensed bank can never take over
    the id of an existing one, even when the two names slug the same way.
    """
    previous_ids = {
        bank["identifiers"][key_scheme]: bank["id"] for bank in previous_banks if key_scheme in bank.get("identifiers", {})
    }
    taken: set[str] = set()
    ids: list[str | None] = []
    for record in records:
        reused = previous_ids.get(record["identifiers"].get(key_scheme))
        if reused in taken:
            reused = None
        ids.append(reused)
        if reused:
            taken.add(reused)
    taken.update(previous_ids.values())

    banks = []
    for record, bank_id in zip(records, ids, strict=True):
        if bank_id is None:
            base = slugify(record["name"])
            bank_id, suffix = base, 2
            while bank_id in taken:
                bank_id, suffix = f"{base}-{suffix}", suffix + 1
            taken.add(bank_id)
        banks.append({"id": bank_id, **record})
    return banks


def summarize_changes(previous_banks: list[dict[str, Any]], banks: list[dict[str, Any]]) -> list[str]:
    """Describe added, removed and changed banks between two versions of a file."""
    before = {bank["id"]: bank for bank in previous_banks}
    after = {bank["id"]: bank for bank in banks}
    added = sorted(after.keys() - before.keys())
    removed = sorted(before.keys() - after.keys())
    changed = sorted(bank_id for bank_id in after.keys() & before.keys() if after[bank_id] != before[bank_id])
    if not (added or removed or changed):
        return ["No bank changes since the last refresh."]
    lines = [f"{len(added)} added, {len(removed)} removed, {len(changed)} changed."]
    lines += [f"+ {after[bank_id]['name']} ({bank_id})" for bank_id in added]
    lines += [f"- {before[bank_id]['name']} ({bank_id})" for bank_id in removed]
    lines += [f"~ {after[bank_id]['name']} ({bank_id})" for bank_id in changed]
    return lines


def _read_previous(path: Path) -> dict[str, Any]:
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    return previous if isinstance(previous, dict) else {}


if __name__ == "__main__":
    sys.exit(main())
