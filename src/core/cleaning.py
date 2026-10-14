"""Cleanup helpers shared by the country refresh modules.

Official registers are maintained by hand, so names arrive with stray line
breaks, trailing spaces and double spaces. These helpers fix spacing only;
they never rewrite what a value says, including its capitalization.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

_PLACEHOLDERS = frozenset({"", "-", "--", "n/a", "na", "nil", "none", "null"})
_LEGAL_SUFFIXES = frozenset({"plc", "ltd", "limited"})
_FORMER_NAME = re.compile(r"\((?:formerly|former)\b[^)]*\)", re.IGNORECASE)


def clean_text(value: Any) -> str | None:
    """Collapse all whitespace to single spaces; return None for blanks and placeholders."""
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return None if cleaned.casefold() in _PLACEHOLDERS else cleaned


def slugify(name: str) -> str:
    """Make a URL-safe id from a bank name, dropping "(Formerly ...)" and a trailing Plc/Ltd/Limited."""
    name = _FORMER_NAME.sub(" ", name)
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[a-z0-9]+", ascii_name.lower())
    while len(words) > 1 and words[-1] in _LEGAL_SUFFIXES:
        words.pop()
    return "-".join(words) or "bank"
