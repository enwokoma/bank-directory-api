"""Tests for looking up registered countries."""

import pytest

from src.countries.nigeria.profile import NIGERIA_PROFILE
from src.countries.registry import get_country_profile, list_country_profiles


@pytest.mark.parametrize("code", ["NG", "ng", "NGA", "nga", " Ng "])
def test_finds_a_country_by_alpha2_or_alpha3_code(code):
    assert get_country_profile(code) is NIGERIA_PROFILE


@pytest.mark.parametrize("code", ["XX", "NIG", "", None])
def test_unknown_or_missing_codes_find_nothing(code):
    assert get_country_profile(code) is None


def test_lists_profiles_by_country_name():
    profiles = list_country_profiles()
    assert NIGERIA_PROFILE in profiles
    assert [profile.name for profile in profiles] == sorted(profile.name for profile in profiles)


def test_every_profile_can_be_refreshed_and_keeps_ids_stable():
    for profile in list_country_profiles():
        assert profile.refresh_module
        assert profile.identifier_schemes, f"{profile.name} needs an identifier scheme to keep bank ids stable"
        assert len(set(profile.bank_type_codes())) == len(profile.bank_types)
