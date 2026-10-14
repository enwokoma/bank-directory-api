"""Tests for turning the CBN register's category lists into Nigeria's dataset."""

import json
from pathlib import Path

import pytest

from src.countries.nigeria import mobile_money, nibss_codes, nip
from src.countries.nigeria import refresh as nigeria_refresh

FIXTURES = Path(__file__).parent / "fixtures" / "nigeria"
NIP_URL = "https://nip.example.test/institutions"


class FixtureClient:
    """Answer each CBN list endpoint from a saved sample of its real response."""

    def __init__(self, overrides=None):
        self.overrides = overrides or {}
        self.nip_headers = "not called"

    def get_json(self, url, params=None, headers=None):
        if url == NIP_URL:
            self.nip_headers = headers
            return json.loads((FIXTURES / "nip_institutions.json").read_text(encoding="utf-8"))
        endpoint = url.removeprefix(nigeria_refresh.CBN_BASE_URL + "/api/")
        if endpoint in self.overrides:
            return self.overrides[endpoint]
        return json.loads((FIXTURES / f"{endpoint}.json").read_text(encoding="utf-8"))

    def get_text(self, url, params=None, headers=None):
        assert url == mobile_money.PSP_PAGE_URL
        return self.overrides.get("PSPs.html") or (FIXTURES / "PSPs.html").read_text(encoding="utf-8")


def by_name(banks):
    return {bank["name"]: bank for bank in banks}


def test_builds_records_from_every_category():
    dataset = nigeria_refresh.fetch_dataset(FixtureClient())
    banks = by_name(dataset["banks"])
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
        "mobile_money",
    }
    assert dataset["sources"] == [nigeria_refresh.SOURCE, mobile_money.SOURCE]


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


def test_adds_licensed_mobile_money_operators():
    banks = by_name(nigeria_refresh.fetch_dataset(FixtureClient())["banks"])
    assert banks["Opay Digital Services Limited (Formerly Paycom Nigeria Limited)"] == {
        "name": "Opay Digital Services Limited (Formerly Paycom Nigeria Limited)",
        "type": "mobile_money",
        "identifiers": {},
    }
    assert sum(1 for bank in banks.values() if bank["type"] == "mobile_money") == 17


def test_reads_only_the_mobile_money_table():
    names = mobile_money.parse_mobile_money_operators((FIXTURES / "PSPs.html").read_text(encoding="utf-8"))
    assert names[0] == "Abeg Technologies Limited"
    assert names[-1] == "Xpress MTS Limited"
    assert "Visa International Service Association" not in names
    assert "Interswitch Limited" not in names


def test_page_without_mobile_money_operators_stops_the_refresh():
    with pytest.raises(ValueError, match="no mobile money operators"):
        nigeria_refresh.fetch_dataset(FixtureClient({"PSPs.html": "<html><h3>A. CARD SCHEMES</h3></html>"}))


def codes(dataset):
    return {bank["name"]: bank["identifiers"].get("nibss_code") for bank in dataset["banks"]}


class TestNibssCodes:
    @pytest.fixture
    def nip_list(self, monkeypatch, tmp_path):
        matches = tmp_path / "matches.json"
        matches.write_text('{"Pagatech Limited": "100002"}', encoding="utf-8")
        monkeypatch.setattr(nibss_codes, "MATCHES_FILE", matches)
        monkeypatch.setenv(nip.ENV_URL, NIP_URL)
        monkeypatch.setenv(nip.ENV_API_KEY, "test-key")

    def test_matches_codes_from_the_configured_list(self, nip_list):
        client = FixtureClient()
        dataset = nigeria_refresh.fetch_dataset(client, [])
        found = codes(dataset)
        assert found["Access Bank Plc"] == "000014"
        assert found["Unity Bank Plc"] == "000011"
        assert found["9 PSB Ltd"] == "120001"
        assert found["Opay Digital Services Limited (Formerly Paycom Nigeria Limited)"] == "100004"
        assert found["Pagatech Limited"] == "100002"
        assert found["1Trust Microfinance Bank Limited"] is None
        assert dataset["sources"][-1] == nip.SOURCE
        assert client.nip_headers == {"X-API-Key": "test-key"}

    def test_reports_what_still_needs_review(self, nip_list, caplog):
        caplog.set_level("INFO")
        nigeria_refresh.fetch_dataset(FixtureClient(), [])
        assert "unused: 000005 ACCESS(DIAMOND) BANK" in caplog.text
        assert "A PAYMENT PROCESSOR" not in caplog.text
        assert "no code: Adamawa Mortgage Bank Limited (mortgage)" in caplog.text

    def test_without_a_list_keeps_the_codes_already_in_the_file(self):
        previous = [
            {
                "id": "access-bank",
                "name": "Access Bank Plc",
                "type": "commercial",
                "identifiers": {"cbn_institution_id": "1", "nibss_code": "000014"},
            },
            {
                "id": "opay-digital-services",
                "name": "Opay Digital Services Limited (Formerly Paycom Nigeria Limited)",
                "type": "mobile_money",
                "identifiers": {"nibss_code": "100004"},
            },
        ]
        client = FixtureClient()
        dataset = nigeria_refresh.fetch_dataset(client, previous)
        found = codes(dataset)
        assert found["Access Bank Plc"] == "000014"
        assert found["Opay Digital Services Limited (Formerly Paycom Nigeria Limited)"] == "100004"
        assert found["Unity Bank Plc"] is None
        assert dataset["sources"][-1] == nip.SOURCE
        assert client.nip_headers == "not called"

    def test_without_a_list_or_earlier_codes_does_not_cite_nip(self):
        dataset = nigeria_refresh.fetch_dataset(FixtureClient(), [])
        assert nip.SOURCE not in dataset["sources"]
        assert set(codes(dataset).values()) == {None}
