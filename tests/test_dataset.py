"""Dataset validation tests."""

import copy

import pytest

from src.core.dataset import search_text, validate_dataset
from src.countries.nigeria.profile import NIGERIA_PROFILE

VALID = {
    "country": "NGA",
    "retrieved_on": "2026-10-14",
    "sources": [{"name": "Central Bank of Nigeria", "url": "https://www.cbn.gov.ng/"}],
    "banks": [
        {"id": "access-bank", "name": "Access Bank Plc", "type": "commercial", "identifiers": {"cbn_institution_id": "1"}},
        {"id": "zenith-bank", "name": "Zenith Bank Plc", "type": "commercial", "identifiers": {"cbn_institution_id": "24"}},
    ],
}


def with_changes(change):
    raw = copy.deepcopy(VALID)
    change(raw)
    return raw


def test_valid_dataset_has_no_errors():
    assert validate_dataset(VALID, NIGERIA_PROFILE) == []


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda raw: raw.update(country="GHA"), "country must be 'NGA'"),
        (lambda raw: raw.update(retrieved_on="14/10/2026"), "retrieved_on must be an ISO date"),
        (lambda raw: raw.update(extra=True), "Top-level keys"),
        (lambda raw: raw.update(sources=[]), "sources must be a non-empty list"),
        (lambda raw: raw["sources"][0].update(url="cbn.gov.ng"), "sources[0].url"),
        (lambda raw: raw.update(banks=[]), "banks must be a non-empty list"),
        (lambda raw: raw["banks"][1].update(id="access-bank"), "used more than once"),
        (lambda raw: raw["banks"][0].update(id="Access Bank"), "lowercase slug"),
        (lambda raw: raw["banks"][0].update(name="Access  Bank Plc"), "name must be non-empty text"),
        (lambda raw: raw["banks"][0].update(type="savings"), "type 'savings'"),
        (lambda raw: raw["banks"][0].update(website="https://example.com"), "unknown keys ['website']"),
        (lambda raw: raw["banks"][0].pop("identifiers"), "missing keys ['identifiers']"),
        (lambda raw: raw["banks"][0]["identifiers"].update(swift="ABNGNGLA"), "identifier scheme 'swift'"),
        (lambda raw: raw["banks"].reverse(), "sorted by name"),
    ],
)
def test_reports_each_problem(change, expected):
    errors = validate_dataset(with_changes(change), NIGERIA_PROFILE)
    assert any(expected in error for error in errors), errors


def test_rejects_non_object():
    assert validate_dataset([], NIGERIA_PROFILE) == ["The file must contain a JSON object."]


def test_search_text_folds_case_accents_and_spacing():
    assert search_text("  Banque  Populaire de CÔTE d'Ivoire ") == "banque populaire de cote d'ivoire"
