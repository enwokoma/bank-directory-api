"""Country-profile registry.

Country-specific details live in country folders such as `src/countries/nigeria/`;
this module only collects them and resolves the country codes callers send.
"""

from __future__ import annotations

from src.countries.nigeria.profile import NIGERIA_PROFILE
from src.countries.profile import CountryProfile

COUNTRY_PROFILES: dict[str, CountryProfile] = {
    NIGERIA_PROFILE.alpha3: NIGERIA_PROFILE,
}

_PROFILES_BY_CODE: dict[str, CountryProfile] = {
    code: profile for profile in COUNTRY_PROFILES.values() for code in (profile.alpha2, profile.alpha3)
}


def get_country_profile(country_code: str | None) -> CountryProfile | None:
    """Look up a profile by ISO 3166-1 alpha-2 or alpha-3 code, ignoring case."""
    if not country_code:
        return None
    return _PROFILES_BY_CODE.get(country_code.strip().upper())


def list_country_profiles() -> list[CountryProfile]:
    """Return every registered profile, sorted by country name."""
    return sorted(COUNTRY_PROFILES.values(), key=lambda profile: profile.name)
