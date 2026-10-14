"""Nigeria's licensed mobile money operators, read from the CBN's payments pages.

The CBN's Payments System > Payment Service Providers page lists every licence
category in its own HTML table under a lettered heading. Operators such as
OPay and PalmPay hold the mobile money operator licence and receive bank
transfers like banks do, so they belong in a list meant for transfers. The
supervision register's mobile money list is shorter (it omits OPay), so this
page is the source.
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any

from src.core.cleaning import clean_text
from src.core.source_client import SourceClient

PSP_PAGE_URL = "https://www.cbn.gov.ng/PaymentsSystem/PSPs.html"
SOURCE = {"name": "Central Bank of Nigeria: Payment Service Providers", "url": PSP_PAGE_URL}
MOBILE_MONEY_HEADING = "MOBILE MONEY OPERATOR"


def fetch_mobile_money_operators(client: SourceClient) -> list[dict[str, Any]]:
    """Return one record per licensed mobile money operator."""
    names = parse_mobile_money_operators(client.get_text(PSP_PAGE_URL))
    return [{"name": name, "type": "mobile_money", "identifiers": {}} for name in names]


def parse_mobile_money_operators(page: str) -> list[str]:
    """Return the licensee names in the table under the mobile money heading."""
    parser = _HeadingsAndRows()
    parser.feed(page)
    names: list[str] = []
    inside = False
    for kind, value in parser.events:
        if kind == "heading":
            if inside:
                break
            inside = MOBILE_MONEY_HEADING in value.upper()
        elif inside:
            name = clean_text(value[-1])
            if name:
                names.append(name)
    if not names:
        raise ValueError("The CBN payment service providers page lists no mobile money operators.")
    return names


class _HeadingsAndRows(HTMLParser):
    """Collect headings and table rows (as lists of cell text) in page order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[tuple[str, Any]] = []
        self._text: list[str] | None = None
        self._row: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"h1", "h2", "h3", "h4", "td"}:
            self._text = []
        elif tag == "tr":
            self._row = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h1", "h2", "h3", "h4"} and self._text is not None:
            self.events.append(("heading", " ".join("".join(self._text).split())))
            self._text = None
        elif tag == "td" and self._text is not None and self._row is not None:
            self._row.append(" ".join("".join(self._text).split()))
            self._text = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.events.append(("row", self._row))
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._text is not None:
            self._text.append(data)
