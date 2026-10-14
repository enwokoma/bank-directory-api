"""Checks every committed country data file, so a bad refresh cannot be merged."""

from src.core.dataset import DATA_DIR, load_datasets
from src.countries.registry import list_country_profiles


def test_committed_data_files_are_valid():
    datasets = load_datasets(DATA_DIR)
    assert set(datasets) == {profile.alpha3 for profile in list_country_profiles()}
