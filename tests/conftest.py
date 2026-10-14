"""Shared test setup."""

import pytest

from src import refresh
from src.countries.nigeria import nip


@pytest.fixture(autouse=True)
def isolate_from_local_settings(monkeypatch, tmp_path):
    """Never read the developer's .env or call a real NIP list from tests."""
    monkeypatch.setattr(refresh, "ENV_FILE", tmp_path / "no.env")
    for name in (nip.ENV_URL, nip.ENV_API_KEY, nip.ENV_KEY_HEADER):
        monkeypatch.delenv(name, raising=False)
