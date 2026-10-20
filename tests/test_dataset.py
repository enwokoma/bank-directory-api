"""Dataset validation tests."""

import copy
import dataclasses
import json

import pytest

from src.core.dataset import DatasetError, load_datasets, search_text, validate_dataset
from src.countries.nigeria.profile import NIGERIA_PROFILE

VALID = {
    "country": "NGA",
    "retrieved_on": "2026-10-14",
    "sources": [{"name": "Central Bank of Nigeria", "url": "https://www.cbn.gov.ng/"}],
    "banks": [
        {
            "id": "access-bank",
            "name": "Access Bank Plc",
            "trading_name": None,
            "type": "commercial",
            "status": "active",
            "identifiers": {"cbn_institution_id": "1"},
        },
        {
            "id": "zenith-bank",
            "name": "Zenith Bank Plc",
            "trading_name": "Zenith",
            "type": "commercial",
            "status": "delisted",
            "identifiers": {"cbn_institution_id": "24"},
        },
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
        (lambda raw: raw["banks"][0].update(status="closed"), "status 'closed' is not one of"),
        (lambda raw: raw["banks"][0].pop("status"), "missing keys ['status']"),
        (lambda raw: raw["banks"][0].pop("trading_name"), "missing keys ['trading_name']"),
        (lambda raw: raw["banks"][0].update(trading_name="Access Bank Plc"), "trading_name must be null"),
        (lambda raw: raw["banks"][0].update(trading_name=" Access "), "trading_name must be null"),
        (lambda raw: raw["banks"][0].update(trading_name=""), "trading_name must be null"),
    ],
)
def test_reports_each_problem(change, expected):
    errors = validate_dataset(with_changes(change), NIGERIA_PROFILE)
    assert any(expected in error for error in errors), errors


def test_rejects_identifiers_that_break_the_profile_pattern():
    profile = dataclasses.replace(NIGERIA_PROFILE, identifier_patterns={"cbn_institution_id": r"[0-9]+"})
    raw = with_changes(lambda raw: raw["banks"][0]["identifiers"].update(cbn_institution_id="A1"))
    assert validate_dataset(raw, profile) == ["banks[0]: identifier 'cbn_institution_id' value 'A1' does not match '[0-9]+'."]


def test_rejects_an_identifier_value_held_by_two_banks():
    raw = with_changes(lambda raw: raw["banks"][1]["identifiers"].update(cbn_institution_id="1"))
    assert validate_dataset(raw, NIGERIA_PROFILE) == [
        "identifier 'cbn_institution_id' value '1' is shared by access-bank, zenith-bank."
    ]


def test_nigerian_nibss_codes_must_have_six_digits():
    raw = with_changes(lambda raw: raw["banks"][0]["identifiers"].update(nibss_code="044"))
    assert validate_dataset(raw, NIGERIA_PROFILE) == [
        "banks[0]: identifier 'nibss_code' value '044' does not match '[0-9]{6}'."
    ]


def test_rejects_non_object():
    assert validate_dataset([], NIGERIA_PROFILE) == ["The file must contain a JSON object."]


def test_missing_data_file_stops_loading(tmp_path):
    with pytest.raises(DatasetError, match="Missing data file for Nigeria"):
        load_datasets(tmp_path)


def test_data_file_without_profile_stops_loading(tmp_path):
    (tmp_path / "NGA.json").write_text(json.dumps(VALID), encoding="utf-8")
    (tmp_path / "XYZ.json").write_text("{}", encoding="utf-8")
    with pytest.raises(DatasetError, match="XYZ.json"):
        load_datasets(tmp_path)


def test_invalid_json_stops_loading(tmp_path):
    (tmp_path / "NGA.json").write_text("{", encoding="utf-8")
    with pytest.raises(DatasetError, match="not valid JSON"):
        load_datasets(tmp_path)


def test_invalid_data_stops_loading(tmp_path):
    (tmp_path / "NGA.json").write_text(json.dumps(with_changes(lambda raw: raw.update(country="GHA"))), encoding="utf-8")
    with pytest.raises(DatasetError, match="failed validation"):
        load_datasets(tmp_path)


def test_loaded_dataset_indexes_banks_by_id(tmp_path):
    (tmp_path / "NGA.json").write_text(json.dumps(VALID), encoding="utf-8")
    dataset = load_datasets(tmp_path)["NGA"]
    assert dataset.banks_by_id["zenith-bank"]["name"] == "Zenith Bank Plc"
    assert dataset.retrieved_on == "2026-10-14"


def test_search_text_folds_case_accents_and_spacing():
    assert search_text("  Banque  Populaire de CÔTE d'Ivoire ") == "banque populaire de cote d'ivoire"
