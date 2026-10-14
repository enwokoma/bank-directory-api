"""Tests for the refresh command that rebuilds country data files."""

import datetime
import json

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
        banks = refresh.assign_ids([record("Paragon Bank", "1"), record("Paragon Bank Ltd", "2")], [], "cbn_institution_id")
        assert [bank["id"] for bank in banks] == ["paragon-bank", "paragon-bank-2"]

    def test_existing_banks_keep_their_id_after_a_rename(self):
        previous = [
            {"id": "diamond-bank", "name": "Diamond Bank", "type": "commercial", "identifiers": {"cbn_institution_id": "9"}}
        ]
        banks = refresh.assign_ids([record("Access Bank (Diamond)", "9")], previous, "cbn_institution_id")
        assert banks[0]["id"] == "diamond-bank"

    def test_new_bank_cannot_take_an_existing_id(self):
        previous = [
            {"id": "zenith-bank", "name": "Zenith Bank Plc", "type": "commercial", "identifiers": {"cbn_institution_id": "24"}}
        ]
        # The new bank comes first in source order but must not claim zenith-bank.
        banks = refresh.assign_ids(
            [record("Zenith Bank", "99"), record("Zenith Bank Plc", "24")], previous, "cbn_institution_id"
        )
        assert [bank["id"] for bank in banks] == ["zenith-bank-2", "zenith-bank"]

    def test_ids_of_removed_banks_are_not_reused(self):
        previous = [
            {"id": "heritage-bank", "name": "Heritage Bank", "type": "commercial", "identifiers": {"cbn_institution_id": "9"}}
        ]
        banks = refresh.assign_ids([record("Heritage Bank", "77")], previous, "cbn_institution_id")
        assert banks[0]["id"] == "heritage-bank-2"


def test_build_dataset_sorts_banks_and_validates():
    fetched = {"sources": [SOURCE], "banks": [record("Zenith Bank Plc", "24"), record("Access Bank Plc", "1")]}
    dataset = refresh.build_dataset(NIGERIA_PROFILE, fetched, [], datetime.date(2026, 10, 14))
    assert dataset["retrieved_on"] == "2026-10-14"
    assert [bank["id"] for bank in dataset["banks"]] == ["access-bank", "zenith-bank"]
    assert refresh.validate_dataset(dataset, NIGERIA_PROFILE) == []


def test_summarize_changes():
    before = [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}]
    after = [{"id": "b", "name": "B Plc"}, {"id": "c", "name": "C"}]
    assert refresh.summarize_changes(before, after) == ["1 added, 1 removed, 1 changed.", "+ C (c)", "- A (a)", "~ B Plc (b)"]
    assert refresh.summarize_changes(after, after) == ["No bank changes since the last refresh."]


class TestRefreshCommand:
    def test_writes_the_country_file(self, tmp_path, monkeypatch):
        fetched = {"sources": [SOURCE], "banks": [record("Access Bank Plc", "1")]}
        monkeypatch.setattr(nigeria_refresh, "fetch_dataset", lambda client: fetched)
        assert refresh.main(["ng", "--data-dir", str(tmp_path)]) == 0
        written = json.loads((tmp_path / "NGA.json").read_text(encoding="utf-8"))
        assert written["banks"][0]["id"] == "access-bank"

    def test_keeps_the_old_file_when_the_new_data_is_invalid(self, tmp_path, monkeypatch):
        (tmp_path / "NGA.json").write_text("old", encoding="utf-8")
        fetched = {"sources": [SOURCE], "banks": [record("Access Bank Plc", "1", bank_type="savings")]}
        monkeypatch.setattr(refresh, "_read_previous", lambda path: {})
        monkeypatch.setattr(nigeria_refresh, "fetch_dataset", lambda client: fetched)
        assert refresh.main(["NGA", "--data-dir", str(tmp_path)]) == 1
        assert (tmp_path / "NGA.json").read_text(encoding="utf-8") == "old"

    @pytest.mark.parametrize("error", [SourceError("CBN is down"), ValueError("CBN returned no institutions")])
    def test_keeps_the_old_file_when_the_source_fails(self, tmp_path, monkeypatch, error):
        def fail(client):
            raise error

        monkeypatch.setattr(nigeria_refresh, "fetch_dataset", fail)
        assert refresh.main(["NGA", "--data-dir", str(tmp_path)]) == 1
        assert not (tmp_path / "NGA.json").exists()

    def test_rejects_unknown_country(self, tmp_path):
        with pytest.raises(SystemExit):
            refresh.main(["XX", "--data-dir", str(tmp_path)])

    def test_all_refreshes_every_registered_country(self, tmp_path, monkeypatch):
        fetched = {"sources": [SOURCE], "banks": [record("Access Bank Plc", "1")]}
        monkeypatch.setattr(nigeria_refresh, "fetch_dataset", lambda client: fetched)
        assert refresh.main(["all", "--data-dir", str(tmp_path)]) == 0
        assert sorted(path.name for path in tmp_path.iterdir()) == ["NGA.json"]


class TestCheckMode:
    def write_current(self, tmp_path, monkeypatch, banks):
        monkeypatch.setattr(nigeria_refresh, "fetch_dataset", lambda client: {"sources": [SOURCE], "banks": banks})
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
            lambda client: {"sources": [SOURCE], "banks": [record("Access Bank Plc", "1"), record("Zenith Bank Plc", "24")]},
        )
        assert refresh.main(["NGA", "--check", "--data-dir", str(tmp_path)]) == 1
        assert (tmp_path / "NGA.json").read_text(encoding="utf-8") == before
        assert "+ Zenith Bank Plc (zenith-bank)" in caplog.text
