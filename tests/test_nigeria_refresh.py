"""Tests for turning the CBN register's category lists into Nigeria's dataset."""

import json
from pathlib import Path

import pytest

from src.countries.nigeria import cbn_bank_codes, mobile_money, nibss_codes, nip
from src.countries.nigeria import refresh as nigeria_refresh

FIXTURES = Path(__file__).parent / "fixtures" / "nigeria"
NIP_URL = "https://nip.example.test/institutions"
NIP_URL_2 = "https://other.example.test/banks"


class FixtureClient:
    """Answer each CBN list endpoint from a saved sample of its real response."""

    def __init__(self, overrides=None):
        self.overrides = overrides or {}
        self.nip_headers = "not called"

    def get_json(self, url, params=None, headers=None):
        if url == NIP_URL:
            self.nip_headers = headers
            return json.loads((FIXTURES / "nip_institutions.json").read_text(encoding="utf-8"))
        if url == NIP_URL_2:
            return json.loads((FIXTURES / "nip_institutions_2.json").read_text(encoding="utf-8"))
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
        "trading_name": "Access Bank Plc",
        "type": "commercial",
        "identifiers": {"cbn_institution_id": "1", "cbn_bank_code": "044"},
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
    assert dataset["sources"] == [nigeria_refresh.SOURCE, mobile_money.SOURCE, cbn_bank_codes.SOURCE]


def test_cleans_spacing_without_changing_capitalization():
    banks = by_name(nigeria_refresh.fetch_dataset(FixtureClient())["banks"])
    assert "Unity Bank Plc" in banks
    assert "MOMO PAYMENT SERVICE BANK" in banks
    assert "TAJ" in banks


def test_keeps_one_record_per_duplicated_name():
    banks = [bank for bank in nigeria_refresh.fetch_dataset(FixtureClient())["banks"] if bank["name"].startswith("Katsu")]
    assert banks == [
        {
            "name": "Katsu Microfinance Bank Limited",
            "trading_name": "Katsu Microfinance Bank Limited",
            "type": "microfinance",
            "identifiers": {"cbn_institution_id": "10009"},
        }
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
        "trading_name": "Opay Digital Services Limited (Formerly Paycom Nigeria Limited)",
        "type": "mobile_money",
        "identifiers": {},
    }
    assert sum(1 for bank in banks.values() if bank["type"] == "mobile_money") == 17


def test_adds_reviewed_trading_names(tmp_path, monkeypatch, caplog):
    names = tmp_path / "trading_names.json"
    names.write_text(json.dumps({"Abeg Technologies Limited": "Pocket", "Gone MFB": "Gone"}), encoding="utf-8")
    monkeypatch.setattr(nigeria_refresh, "TRADING_NAMES_FILE", names)
    banks = by_name(nigeria_refresh.fetch_dataset(FixtureClient())["banks"])
    assert banks["Abeg Technologies Limited"]["trading_name"] == "Pocket"
    assert banks["Access Bank Plc"]["trading_name"] == "Access Bank Plc"
    assert "Trading name for 'Gone MFB' names no bank in the register." in caplog.text


def test_adds_reviewed_cbn_bank_codes(tmp_path, monkeypatch, caplog):
    codes = tmp_path / "cbn_bank_codes.json"
    codes.write_text(json.dumps({"Access Bank Plc": "044", "Gone MFB": "50999"}), encoding="utf-8")
    monkeypatch.setattr(cbn_bank_codes, "CODES_FILE", codes)
    dataset = nigeria_refresh.fetch_dataset(FixtureClient())
    banks = by_name(dataset["banks"])
    assert banks["Access Bank Plc"]["identifiers"]["cbn_bank_code"] == "044"
    assert "cbn_bank_code" not in banks["Unity Bank Plc"]["identifiers"]
    assert cbn_bank_codes.SOURCE in dataset["sources"]
    assert "CBN bank code for 'Gone MFB' names no bank in the register." in caplog.text


def test_without_any_cbn_bank_code_does_not_cite_their_source(tmp_path, monkeypatch):
    codes = tmp_path / "cbn_bank_codes.json"
    codes.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cbn_bank_codes, "CODES_FILE", codes)
    assert cbn_bank_codes.SOURCE not in nigeria_refresh.fetch_dataset(FixtureClient())["sources"]


def test_committed_cbn_bank_codes_are_in_the_data_file():
    codes = json.loads(cbn_bank_codes.CODES_FILE.read_text(encoding="utf-8"))
    dataset = json.loads((Path(__file__).parents[1] / "data" / "countries" / "NGA.json").read_text(encoding="utf-8"))
    in_file = {
        bank["name"]: bank["identifiers"]["cbn_bank_code"]
        for bank in dataset["banks"]
        if "cbn_bank_code" in bank["identifiers"]
    }
    assert in_file == codes
    assert cbn_bank_codes.SOURCE in dataset["sources"]


def test_committed_trading_names_name_banks_in_the_register():
    names = json.loads(nigeria_refresh.TRADING_NAMES_FILE.read_text(encoding="utf-8"))
    dataset = json.loads((Path(__file__).parents[1] / "data" / "countries" / "NGA.json").read_text(encoding="utf-8"))
    trading = {bank["name"]: bank["trading_name"] for bank in dataset["banks"] if bank["trading_name"] != bank["name"]}
    assert trading == names


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

    def test_merges_a_second_list(self, nip_list, monkeypatch, caplog):
        caplog.set_level("INFO")
        monkeypatch.setenv(nip.ENV_URL + "_2", NIP_URL_2)
        client = FixtureClient({"GetDMBs": [{"id": 1, "name": "Access Bank Plc"}, {"id": 9865, "name": "Optimus Bank"}]})
        found = codes(nigeria_refresh.fetch_dataset(client, []))
        assert found["Optimus Bank"] == "000036"
        assert found["Access Bank Plc"] == "000014"
        assert "NIP institution list 1 has 16 institutions" in caplog.text
        assert "NIP institution list 2 has 3 institutions" in caplog.text

    def test_reports_what_still_needs_review(self, nip_list, caplog):
        caplog.set_level("INFO")
        nigeria_refresh.fetch_dataset(FixtureClient(), [])
        assert "unused: 000005 ACCESS(DIAMOND) BANK" in caplog.text
        assert "A PAYMENT PROCESSOR" not in caplog.text
        assert "no code: Adamawa Mortgage Bank Limited (mortgage)" in caplog.text

    def test_lists_every_match_when_verbose(self, nip_list, caplog):
        caplog.set_level("DEBUG")
        nigeria_refresh.fetch_dataset(FixtureClient(), [])
        assert "matched (automatic): Access Bank Plc -> 000014 ACCESS BANK" in caplog.text
        assert "matched (reviewed): Pagatech Limited -> 100002 PAGA" in caplog.text

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
