"""The NIBSS Instant Payment (NIP) institution list, and the lists that relay it.

NIBSS gives every institution that can receive NIP transfers a 6-digit code
and serves the current list to connected institutions through NIP's
`financialinstitutionlist` operation. NIBSS does not publish the list openly,
so the refresh reads it from APIs that relay it, set on the maintainer's
machine (in `.env`, which git ignores) or as CI secrets:

    NIP_INSTITUTIONS_URL         full URL of the endpoint
    NIP_INSTITUTIONS_API_KEY     key sent with the request, if the endpoint needs one
    NIP_INSTITUTIONS_KEY_HEADER  header that carries the key (default: X-API-Key)
    NIP_INSTITUTIONS_LOGIN_URL   for an endpoint that needs a login first: the key is
                                 "api key:secret key", sent to this URL as Basic auth,
                                 and the list is read with the token the login returns

Relayed copies can be incomplete, so up to five lists can be combined: the
same names ending in _2, _3, _4 and _5 configure more endpoints, and the lists
are merged by code. When no URL is set, the refresh keeps the codes already in
the data file.

Payment providers' lists carry the code the provider takes for each
institution next to the NIBSS code, which for most institutions is the CBN's
(see `cbn_bank_codes.py`); `read_institution_list` keeps both, for the
bank-code report in `bank_code_sources.py`. A list whose own codes are the
6-digit NIBSS codes, as Flutterwave's are for most institutions, is a relay
like the others; one that carries no NIBSS codes at all adds nothing to the
refresh and only serves that report.
"""

from __future__ import annotations

import base64
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.core.cleaning import clean_text
from src.core.source_client import SourceClient, SourceError

ENV_URL = "NIP_INSTITUTIONS_URL"
ENV_API_KEY = "NIP_INSTITUTIONS_API_KEY"
ENV_KEY_HEADER = "NIP_INSTITUTIONS_KEY_HEADER"
ENV_LOGIN_URL = "NIP_INSTITUTIONS_LOGIN_URL"
DEFAULT_KEY_HEADER = "X-API-Key"
MAX_LISTS = 5

SOURCE = {"name": "NIBSS Instant Payment (NIP) institution list", "url": "https://nibss-plc.com.ng/nibss-instant-payment/"}
CODE_PATTERN = r"[0-9]{6}"

# Relaying APIs name their fields differently. Some also return a code of their
# own under a generic name, so when a row has a field that says NIBSS, only
# that field is used, even when it is empty. Paystack's bank list returns
# nip_sort_code only when asked with currency=NGN&include_nip_sort_code=true;
# without it, its rows carry only Paystack's own codes. Monnify's returns
# nipBankCode next to its own code.
_NIBSS_CODE_KEYS = ("nibss_code", "nibss_bank_code", "nip_code", "nip_sort_code", "nipBankCode")
_CODE_KEYS = ("institution_code", "institutionCode", "bankCode", "code")
_NAME_KEYS = ("name", "bankName", "institution_name", "institutionName")
_LIST_KEYS = ("data", "banks", "institutions", "responseBody")
# Where a login answer carries the token to read the list with.
_TOKEN_KEYS = ("accessToken", "access_token", "token")


@dataclass(frozen=True)
class NipSettings:
    url: str
    api_key: str | None
    key_header: str
    # Name of the URL setting, used in error messages instead of the URL.
    setting: str = ENV_URL
    # Set when the endpoint needs a login first; the key is then "api key:secret key".
    login_url: str | None = None

    @property
    def label(self) -> str:
        """ "list 1" for the first setting, "list N" for the ones ending in _N."""
        suffix = self.setting.removeprefix(ENV_URL)
        return f"list {suffix.removeprefix('_') or 1}"


@dataclass(frozen=True)
class NipInstitution:
    code: str
    name: str


@dataclass(frozen=True)
class ListedInstitution:
    """One row of a relayed list: the provider's own code for the institution, and its NIBSS code when given."""

    name: str
    code: str
    nibss_code: str | None


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
                    setting=ENV_URL + suffix,
                    login_url=(environ.get(ENV_LOGIN_URL + suffix) or "").strip() or None,
                )
            )
    return found


def fetch_nip_institutions(client: SourceClient, settings: NipSettings) -> list[NipInstitution]:
    """Fetch a list and keep the institutions that carry a NIBSS code.

    The key is sent as a header and never logged, and errors name the setting
    rather than the endpoint, so neither ends up in a terminal or CI log.
    """
    return [
        NipInstitution(code=row.nibss_code, name=row.name)
        for row in fetch_institution_list(client, settings)
        if row.nibss_code
    ]


def fetch_institution_list(client: SourceClient, settings: NipSettings) -> list[ListedInstitution]:
    """Fetch a list as the provider gives it, logging in first when the endpoint needs that."""
    try:
        headers = _login(client, settings) if settings.login_url else _key_header(settings)
        body = client.get_json(settings.url, headers=headers)
    except SourceError as exc:
        reason = f"answered HTTP {exc.status}" if exc.status else "could not be reached"
        raise SourceError(f"The institution list set in {settings.setting} {reason}.", exc.status) from None
    try:
        return read_institution_list(body)
    except ValueError as exc:
        raise ValueError(f"The institution list set in {settings.setting}: {exc}") from None


def parse_nip_institutions(body: Any) -> list[NipInstitution]:
    """Read the institutions with a NIBSS code from a list, or from a list under a common key such as `data`."""
    return [NipInstitution(code=row.nibss_code, name=row.name) for row in read_institution_list(body) if row.nibss_code]


def read_institution_list(body: Any) -> list[ListedInstitution]:
    """Read every institution a list names, with the provider's code and, when the row carries one, the NIBSS code."""
    rows = _find_rows(body)
    institutions = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        name = next((clean_text(row[key]) for key in _NAME_KEYS if clean_text(row.get(key))), None)
        if not name:
            continue
        nibss_keys = [key for key in _NIBSS_CODE_KEYS if key in row]
        nibss = next((str(row[key]).strip() for key in nibss_keys if row.get(key)), "")
        code = next((str(row[key]).strip() for key in _CODE_KEYS if row.get(key)), "")
        if not nibss_keys and re.fullmatch(CODE_PATTERN, code):
            nibss = code
        if not code and not nibss:
            continue
        institutions.append(
            ListedInstitution(name=name, code=code or nibss, nibss_code=nibss if re.fullmatch(CODE_PATTERN, nibss) else None)
        )
    if not institutions:
        raise ValueError("The institution list response has no institutions with codes.")
    return institutions


def _key_header(settings: NipSettings) -> dict[str, str] | None:
    return {settings.key_header: settings.api_key} if settings.api_key else None


def _login(client: SourceClient, settings: NipSettings) -> dict[str, str]:
    """Log in with the key pair as Basic auth and return the bearer header the list is read with."""
    if not settings.api_key or ":" not in settings.api_key:
        raise ValueError(f"The list set in {settings.setting} needs a login, so its key must be 'api key:secret key'.")
    basic = base64.b64encode(settings.api_key.encode()).decode()
    assert settings.login_url is not None
    answer = client.post_json(settings.login_url, headers={"Authorization": f"Basic {basic}"})
    token = next((value for value in _walk(answer, _TOKEN_KEYS) if isinstance(value, str) and value), None)
    if not token:
        raise ValueError(f"The login for the list set in {settings.setting} returned no token.")
    return {"Authorization": f"Bearer {token}"}


def _walk(body: Any, keys: tuple[str, ...], depth: int = 3) -> list[Any]:
    """Values under any of `keys` in a JSON object, looking a few levels down, as login answers nest them."""
    if not isinstance(body, dict) or depth == 0:
        return []
    found = [body[key] for key in keys if key in body]
    for value in body.values():
        found += _walk(value, keys, depth - 1)
    return found


def _find_rows(body: Any) -> Any:
    for _ in range(3):
        if not isinstance(body, dict):
            break
        body = next((body[key] for key in _LIST_KEYS if key in body), None)
    return body
