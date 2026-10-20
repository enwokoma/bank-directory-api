"""Tests for the refresh command that rebuilds country data files."""

import datetime
import json
import os

import pytest

from src import refresh
from src.core.source_client import SourceError
from src.countries.nigeria import refresh as nigeria_refresh
from src.countries.nigeria.profile import NIGERIA_PROFILE

SOURCE = {"name": "Central Bank of Nigeria", "url": "https://www.cbn.gov.ng/"}


def record(name, cbn_id, bank_type="commercial"):
    return {"name": name, "type": bank_type, "identifiers": {"cbn_institution_id": cbn_id}}


class TestAssignIds:
    def test_new_banks_get_slugs_and_collisions_get_a_suffix(self):
        banks = refresh.assign_ids([record("Paragon Bank", "1"), record("Paragon Bank Ltd", "2")], [], ["cbn_institution_id"])
        assert [bank["id"] for bank in banks] == ["paragon-bank", "paragon-bank-2"]

    def test_existing_banks_keep_their_id_after_a_rename(self):
        previous = [
            {"id": "diamond-bank", "name": "Diamond Bank", "type": "commercial", "identifiers": {"cbn_institution_id": "9"}}
        ]
        banks = refresh.assign_ids([record("Access Bank (Diamond)", "9")], previous, ["cbn_institution_id"])
        assert banks[0]["id"] == "diamond-bank"

    def test_new_bank_cannot_take_an_existing_id(self):
        previous = [
            {"id": "zenith-bank", "name": "Zenith Bank Plc", "type": "commercial", "identifiers": {"cbn_institution_id": "24"}}
        ]
        # The new bank comes first in source order but must not claim zenith-bank.
        banks = refresh.assign_ids(
            [record("Zenith Bank", "99"), record("Zenith Bank Plc", "24")], previous, ["cbn_institution_id"]
        )
        assert [bank["id"] for bank in banks] == ["zenith-bank-2", "zenith-bank"]

    def test_ids_of_removed_banks_are_not_reused(self):
        previous = [
            {"id": "heritage-bank", "name": "Heritage Bank", "type": "commercial", "identifiers": {"cbn_institution_id": "9"}}
        ]
        banks = refresh.assign_ids([record("Heritage Bank", "77")], previous, ["cbn_institution_id"])
        assert banks[0]["id"] == "heritage-bank-2"

    def test_a_bank_without_the_first_identifier_keeps_its_id_through_another_one(self):
        previous = [
            {"id": "opay-digital-services", "name": "OPay Digital Services Limited", "identifiers": {"nibss_code": "100004"}}
        ]
        renamed = {"name": "OPay Limited", "type": "mobile_money", "identifiers": {"nibss_code": "100004"}}
        banks = refresh.assign_ids([renamed], previous, ["cbn_institution_id", "nibss_code"])
        assert banks[0]["id"] == "opay-digital-services"

    def test_a_bank_without_identifiers_keeps_its_id_by_name(self):
        previous = [{"id": "visual-ict", "name": "Visual ICT Limited", "identifiers": {}}]
        operator = {"name": "Visual ICT Limited", "type": "mobile_money", "identifiers": {}}
        banks = refresh.assign_ids([operator], previous, ["cbn_institution_id", "nibss_code"])
        assert banks[0]["id"] == "visual-ict"

    def test_ids_of_renamed_banks_without_identifiers_stay_reserved(self):
        previous = [{"id": "visual-ict", "name": "Visual ICT Limited", "identifiers": {}}]
        newcomer = {"name": "Visual ICT", "type": "mobile_money", "identifiers": {}}
        banks = refresh.assign_ids([newcomer], previous, ["cbn_institution_id"])
        assert banks[0]["id"] == "visual-ict-2"


def test_build_dataset_sorts_banks_and_validates():
    fetched = {"sources": [SOURCE], "banks": [record("Zenith Bank Plc", "24"), record("Access Bank Plc", "1")]}
    dataset = refresh.build_dataset(NIGERIA_PROFILE, fetched, [], datetime.date(2026, 10, 14))
    assert dataset["retrieved_on"] == "2026-10-14"
    assert [bank["id"] for bank in dataset["banks"]] == ["access-bank", "zenith-bank"]
    assert list(dataset["banks"][0]) == ["id", "name", "type", "status", "identifiers"]
    assert {bank["status"] for bank in dataset["banks"]} == {"active"}
    assert refresh.validate_dataset(dataset, NIGERIA_PROFILE) == []


class TestDelisting:
    def build(self, banks, previous):
        fetched = {"sources": [SOURCE], "banks": banks}
        dataset = refresh.build_dataset(NIGERIA_PROFILE, fetched, previous, datetime.date(2026, 10, 14))
        assert refresh.validate_dataset(dataset, NIGERIA_PROFILE) == []
        return {bank["id"]: bank for bank in dataset["banks"]}

    def test_a_bank_the_source_no_longer_lists_stays_delisted(self):
        first = self.build([record("Access Bank Plc", "1"), record("Heritage Bank Plc", "9")], [])
        banks = self.build([record("Access Bank Plc", "1")], list(first.values()))
        assert banks["heritage-bank"]["status"] == "delisted"
        assert banks["heritage-bank"]["identifiers"] == {"cbn_institution_id": "9"}
        assert banks["access-bank"]["status"] == "active"

    def test_a_delisted_bank_stays_delisted(self):
        first = self.build([record("Access Bank Plc", "1"), record("Heritage Bank Plc", "9")], [])
        second = self.build([record("Access Bank Plc", "1")], list(first.values()))
        third = self.build([record("Access Bank Plc", "1")], list(second.values()))
        assert third == second

    def test_a_bank_listed_again_is_active_under_its_old_id(self):
        first = self.build([record("Access Bank Plc", "1"), record("Heritage Bank Plc", "9")], [])
        second = self.build([record("Access Bank Plc", "1")], list(first.values()))
        third = self.build([record("Access Bank Plc", "1"), record("Heritage Bank", "9")], list(second.values()))
        assert third["heritage-bank"]["status"] == "active"
        assert third["heritage-bank"]["name"] == "Heritage Bank"

    def test_an_identifier_now_held_by_a_listed_bank_leaves_the_delisted_one(self):
        def wallet(name, cbn_id, nibss_code=None):
            identifiers = {"cbn_institution_id": cbn_id} | ({"nibss_code": nibss_code} if nibss_code else {})
            return {"name": name, "type": "mobile_money", "identifiers": identifiers}

        first = self.build([wallet("Old Wallet Limited", "5", "100004"), wallet("New Wallet Limited", "6")], [])
        banks = self.build([wallet("New Wallet Limited", "6", "100004")], list(first.values()))
        assert banks["new-wallet"]["identifiers"] == {"cbn_institution_id": "6", "nibss_code": "100004"}
        assert banks["old-wallet"]["identifiers"] == {"cbn_institution_id": "5"}
        assert banks["old-wallet"]["status"] == "delisted"

    def test_banks_from_a_file_without_statuses_can_be_delisted(self):
        previous = [
            {
                "id": "heritage-bank",
                "name": "Heritage Bank Plc",
                "type": "commercial",
                "identifiers": {"cbn_institution_id": "9"},
            }
        ]
        banks = self.build([record("Access Bank Plc", "1")], previous)
        assert banks["heritage-bank"]["status"] == "delisted"


def test_summarize_changes():
    before = [
        {"id": "a", "name": "A", "status": "active"},
        {"id": "b", "name": "B", "status": "active"},
        {"id": "d", "name": "D", "status": "delisted"},
    ]
    after = [
        {"id": "a", "name": "A", "status": "delisted"},
        {"id": "b", "name": "B Plc", "status": "active"},
        {"id": "c", "name": "C", "status": "active"},
        {"id": "d", "name": "D", "status": "active"},
    ]
    assert refresh.summarize_changes(before, after) == [
        "1 added, 1 delisted, 1 relisted, 1 changed.",
        "+ C (c)",
        "- A (a)",
        "^ D (d)",
        "~ B Plc (b)",
    ]
    assert refresh.summarize_changes(after, after) == ["No bank changes since the last refresh."]


class TestRefreshCommand:
    def test_writes_the_country_file(self, tmp_path, monkeypatch):
        fetched = {"sources": [SOURCE], "banks": [record("Access Bank Plc", "1")]}
        monkeypatch.setattr(nigeria_refresh, "fetch_dataset", lambda client, previous: fetched)
        assert refresh.main(["ng", "--data-dir", str(tmp_path)]) == 0
        written = json.loads((tmp_path / "NGA.json").read_text(encoding="utf-8"))
        assert written["banks"][0]["id"] == "access-bank"

    def test_keeps_the_old_file_when_the_new_data_is_invalid(self, tmp_path, monkeypatch):
        (tmp_path / "NGA.json").write_text("old", encoding="utf-8")
        fetched = {"sources": [SOURCE], "banks": [record("Access Bank Plc", "1", bank_type="savings")]}
        monkeypatch.setattr(refresh, "_read_previous", lambda path: {})
        monkeypatch.setattr(nigeria_refresh, "fetch_dataset", lambda client, previous: fetched)
        assert refresh.main(["NGA", "--data-dir", str(tmp_path)]) == 1
        assert (tmp_path / "NGA.json").read_text(encoding="utf-8") == "old"

    @pytest.mark.parametrize("error", [SourceError("CBN is down"), ValueError("CBN returned no institutions")])
    def test_keeps_the_old_file_when_the_source_fails(self, tmp_path, monkeypatch, error):
        def fail(client, previous):
            raise error

        monkeypatch.setattr(nigeria_refresh, "fetch_dataset", fail)
        assert refresh.main(["NGA", "--data-dir", str(tmp_path)]) == 1
        assert not (tmp_path / "NGA.json").exists()

    def test_rejects_unknown_country(self, tmp_path):
        with pytest.raises(SystemExit):
            refresh.main(["XX", "--data-dir", str(tmp_path)])

    def test_all_refreshes_every_registered_country(self, tmp_path, monkeypatch):
        fetched = {"sources": [SOURCE], "banks": [record("Access Bank Plc", "1")]}
        monkeypatch.setattr(nigeria_refresh, "fetch_dataset", lambda client, previous: fetched)
        assert refresh.main(["all", "--data-dir", str(tmp_path)]) == 0
        assert sorted(path.name for path in tmp_path.iterdir()) == ["NGA.json"]

    def test_passes_the_previous_banks_to_the_country_module(self, tmp_path, monkeypatch):
        seen = []
        first = {"sources": [SOURCE], "banks": [record("Access Bank Plc", "1")]}
        monkeypatch.setattr(nigeria_refresh, "fetch_dataset", lambda client, previous: seen.append(previous) or first)
        refresh.main(["NGA", "--data-dir", str(tmp_path)])
        refresh.main(["NGA", "--data-dir", str(tmp_path)])
        assert seen[0] == []
        assert [bank["id"] for bank in seen[1]] == ["access-bank"]

    def test_reads_settings_from_the_env_file(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("NIP_INSTITUTIONS_URL=https://example.test/banks\n", encoding="utf-8")
        monkeypatch.setattr(refresh, "ENV_FILE", env_file)
        monkeypatch.delenv("NIP_INSTITUTIONS_URL", raising=False)
        seen = []
        fetched = {"sources": [SOURCE], "banks": [record("Access Bank Plc", "1")]}
        monkeypatch.setattr(
            nigeria_refresh,
            "fetch_dataset",
            lambda client, previous: seen.append(os.environ.get("NIP_INSTITUTIONS_URL")) or fetched,
        )
        refresh.main(["NGA", "--data-dir", str(tmp_path)])
        assert seen == ["https://example.test/banks"]

    def test_environment_values_win_over_the_env_file(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("NIP_INSTITUTIONS_URL=https://file.example.test/\n", encoding="utf-8")
        monkeypatch.setattr(refresh, "ENV_FILE", env_file)
        monkeypatch.setenv("NIP_INSTITUTIONS_URL", "https://env.example.test/")
        seen = []
        fetched = {"sources": [SOURCE], "banks": [record("Access Bank Plc", "1")]}
        monkeypatch.setattr(
            nigeria_refresh,
            "fetch_dataset",
            lambda client, previous: seen.append(os.environ.get("NIP_INSTITUTIONS_URL")) or fetched,
        )
        refresh.main(["NGA", "--data-dir", str(tmp_path)])
        assert seen == ["https://env.example.test/"]


class TestCheckMode:
    def write_current(self, tmp_path, monkeypatch, banks):
        monkeypatch.setattr(nigeria_refresh, "fetch_dataset", lambda client, previous: {"sources": [SOURCE], "banks": banks})
        assert refresh.main(["NGA", "--data-dir", str(tmp_path)]) == 0
        return (tmp_path / "NGA.json").read_text(encoding="utf-8")

    def test_passes_when_the_source_matches(self, tmp_path, monkeypatch):
        before = self.write_current(tmp_path, monkeypatch, [record("Access Bank Plc", "1")])
        assert refresh.main(["NGA", "--check", "--data-dir", str(tmp_path)]) == 0
        assert (tmp_path / "NGA.json").read_text(encoding="utf-8") == before

    def test_fails_without_writing_when_the_source_changed(self, tmp_path, monkeypatch, caplog):
        before = self.write_current(tmp_path, monkeypatch, [record("Access Bank Plc", "1")])
        monkeypatch.setattr(
            nigeria_refresh,
            "fetch_dataset",
            lambda client, previous: {
                "sources": [SOURCE],
                "banks": [record("Access Bank Plc", "1"), record("Zenith Bank Plc", "24")],
            },
        )
        assert refresh.main(["NGA", "--check", "--data-dir", str(tmp_path)]) == 1
        assert (tmp_path / "NGA.json").read_text(encoding="utf-8") == before
        assert "+ Zenith Bank Plc (zenith-bank)" in caplog.text
