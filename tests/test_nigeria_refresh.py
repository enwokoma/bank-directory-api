"""Tests for turning the CBN register's category lists into Nigeria's dataset."""

import json
from pathlib import Path

import pytest

from src.countries.nigeria import refresh as nigeria_refresh

FIXTURES = Path(__file__).parent / "fixtures" / "nigeria"


class FixtureClient:
    """Answer each CBN list endpoint from a saved sample of its real response."""

    def __init__(self, overrides=None):
        self.overrides = overrides or {}

    def get_json(self, url, params=None):
        endpoint = url.removeprefix(nigeria_refresh.CBN_BASE_URL + "/api/")
        if endpoint in self.overrides:
            return self.overrides[endpoint]
        return json.loads((FIXTURES / f"{endpoint}.json").read_text(encoding="utf-8"))


def by_name(banks):
    return {bank["name"]: bank for bank in banks}


def test_builds_records_from_every_category():
    dataset = nigeria_refresh.fetch_dataset(FixtureClient())
    banks = by_name(dataset["banks"])
    assert dataset["sources"] == [nigeria_refresh.SOURCE]
    assert banks["Access Bank Plc"] == {
        "name": "Access Bank Plc",
        "type": "commercial",
        "identifiers": {"cbn_institution_id": "1"},
    }
    assert {bank["type"] for bank in dataset["banks"]} == {
        "commercial",
        "merchant",
        "non_interest",
        "payment_service",
        "microfinance",
        "mortgage",
    }


def test_cleans_spacing_without_changing_capitalization():
    banks = by_name(nigeria_refresh.fetch_dataset(FixtureClient())["banks"])
    assert "Unity Bank Plc" in banks
    assert "MOMO PAYMENT SERVICE BANK" in banks
    assert "TAJ" in banks


def test_keeps_one_record_per_duplicated_name():
    banks = [bank for bank in nigeria_refresh.fetch_dataset(FixtureClient())["banks"] if bank["name"].startswith("Katsu")]
    assert banks == [
        {"name": "Katsu Microfinance Bank Limited", "type": "microfinance", "identifiers": {"cbn_institution_id": "10009"}}
    ]


def test_first_category_wins_when_an_institution_is_listed_twice():
    client = FixtureClient({"GetMBs": [{"id": 1, "name": "Access Bank Plc"}]})
    banks = [bank for bank in nigeria_refresh.fetch_dataset(client)["banks"] if bank["name"] == "Access Bank Plc"]
    assert [bank["type"] for bank in banks] == ["commercial"]


def test_empty_category_stops_the_refresh():
    with pytest.raises(ValueError, match="no institutions for merchant"):
        nigeria_refresh.fetch_dataset(FixtureClient({"GetMBs": []}))


def test_row_without_a_name_stops_the_refresh():
    with pytest.raises(ValueError, match="missing an id or name"):
        nigeria_refresh.fetch_dataset(FixtureClient({"GetPSBs": [{"id": 5, "name": "  "}]}))
