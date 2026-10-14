"""Shared country-profile data shape.

Each country package defines one profile with these classes. The registry in
`registry.py` collects them, and the dataset loader checks every country data
file in `data/countries/` against its profile.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BankType:
    """One category of licensed institution, such as commercial or microfinance."""

    code: str
    name: str


@dataclass(frozen=True)
class CountryProfile:
    """What the API knows about one country before reading its data file."""

    alpha2: str
    alpha3: str
    name: str
    currency: str
    bank_types: tuple[BankType, ...]
    # Identifier scheme code -> human-readable description, for example the
    # regulator's own record ID or a national bank code.
    identifier_schemes: dict[str, str] = field(default_factory=dict)
    # Identifier scheme code -> regular expression every value must fully match.
    identifier_patterns: dict[str, str] = field(default_factory=dict)
    # Dotted module path whose `fetch_dataset()` rebuilds this country's data file.
    refresh_module: str = ""

    def bank_type_codes(self) -> list[str]:
        """Return the bank type codes in the profile's display order."""
        return [bank_type.code for bank_type in self.bank_types]
