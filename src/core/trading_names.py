"""Trading names: the names banks use today where a register still lists an older one.

Registers lag behind renames, so a bank's `name` stays exactly as its register
publishes it and `trading_name` carries the name it trades under, which is the
register name unless a reviewed one says otherwise. Each country
keeps the reviewed names in a JSON object that maps a register name to its
trading name. An entry whose register name no longer appears is reported, so it
can be removed once the register catches up.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_trading_names(path: Path) -> dict[str, str]:
    """Read the reviewed register name -> trading name pairs."""
    names = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(names, dict) or not all(isinstance(value, str) for value in names.values()):
        raise ValueError(f"{path.name} must map register names to trading names.")
    return names


def apply_trading_names(records: list[dict[str, Any]], names: dict[str, str]) -> list[str]:
    """Set `trading_name` on every record, the register name unless a reviewed one exists, and return any problems."""
    problems = []
    for record in records:
        if names.get(record["name"]) == record["name"]:
            problems.append(f"Trading name for {record['name']!r} is the register name; the entry can be removed.")
        record["trading_name"] = names.get(record["name"], record["name"])
    listed = {record["name"] for record in records}
    problems += [f"Trading name for {name!r} names no bank in the register." for name in sorted(set(names) - listed)]
    return problems
