"""The NIBSS Instant Payment (NIP) institution list.

NIBSS gives every institution that can receive NIP transfers a 6-digit code
and serves the current list to connected institutions through NIP's
`financialinstitutionlist` operation. NIBSS does not publish the list openly,
so the refresh reads it from APIs that relay it, set on the maintainer's
machine (in `.env`, which git ignores) or as CI secrets:

    NIP_INSTITUTIONS_URL         full URL of the endpoint
    NIP_INSTITUTIONS_API_KEY     key sent with the request, if the endpoint needs one
    NIP_INSTITUTIONS_KEY_HEADER  header that carries the key (default: X-API-Key)

Relayed copies can be incomplete, so up to five can be combined: the same
names ending in _2, _3, _4 and _5 configure more endpoints, and the lists are
merged by code. When no URL is set, the refresh keeps the codes already in
the data file.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.core.cleaning import clean_text
from src.core.source_client import SourceClient

ENV_URL = "NIP_INSTITUTIONS_URL"
ENV_API_KEY = "NIP_INSTITUTIONS_API_KEY"
ENV_KEY_HEADER = "NIP_INSTITUTIONS_KEY_HEADER"
DEFAULT_KEY_HEADER = "X-API-Key"
MAX_LISTS = 5

SOURCE = {"name": "NIBSS Instant Payment (NIP) institution list", "url": "https://nibss-plc.com.ng/nibss-instant-payment/"}
CODE_PATTERN = r"[0-9]{6}"

# Relaying APIs name their fields differently. Some also return a code of their
# own under a generic name, so when a row has a field that says NIBSS, only
# that field is used, even when it is empty.
_NIBSS_CODE_KEYS = ("nibss_code", "nibss_bank_code", "nip_code")
_CODE_KEYS = ("institution_code", "institutionCode", "bankCode", "code")
_NAME_KEYS = ("name", "bankName", "institution_name", "institutionName")
_LIST_KEYS = ("data", "banks", "institutions")


@dataclass(frozen=True)
class NipSettings:
    url: str
    api_key: str | None
    key_header: str


@dataclass(frozen=True)
class NipInstitution:
    code: str
    name: str


def settings_from_env(environ: Mapping[str, str] = os.environ) -> list[NipSettings]:
    """Return every configured endpoint, in order, or an empty list when no URL is set."""
    found = []
    for suffix in ["", *(f"_{number}" for number in range(2, MAX_LISTS + 1))]:
        url = (environ.get(ENV_URL + suffix) or "").strip()
        if url:
            found.append(
                NipSettings(
                    url=url,
                    api_key=(environ.get(ENV_API_KEY + suffix) or "").strip() or None,
                    key_header=(environ.get(ENV_KEY_HEADER + suffix) or "").strip() or DEFAULT_KEY_HEADER,
                )
            )
    return found


def fetch_nip_institutions(client: SourceClient, settings: NipSettings) -> list[NipInstitution]:
    """Fetch and parse the institution list. The key is sent as a header and never logged."""
    headers = {settings.key_header: settings.api_key} if settings.api_key else None
    return parse_nip_institutions(client.get_json(settings.url, headers=headers))


def parse_nip_institutions(body: Any) -> list[NipInstitution]:
    """Read institutions from a list, or from a list under a common key such as `data`."""
    rows = _find_rows(body)
    institutions = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        keys = [key for key in _NIBSS_CODE_KEYS if key in row] or list(_CODE_KEYS)
        code = next((str(row[key]).strip() for key in keys if row.get(key)), "")
        name = next((clean_text(row[key]) for key in _NAME_KEYS if clean_text(row.get(key))), None)
        if name and re.fullmatch(CODE_PATTERN, code):
            institutions.append(NipInstitution(code=code, name=name))
    if not institutions:
        raise ValueError("The NIP institution list response has no institutions with 6-digit codes.")
    return institutions


def _find_rows(body: Any) -> Any:
    for _ in range(3):
        if not isinstance(body, dict):
            break
        body = next((body[key] for key in _LIST_KEYS if key in body), None)
    return body
