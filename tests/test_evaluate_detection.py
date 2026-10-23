"""Tests for the evaluation and calibration command, on a synthetic CSV: no real account numbers are needed."""

import csv
import json
import re
from collections import Counter

import pytest

from src.core.dataset import load_datasets
from src.countries.nigeria import detection, nuban
from src.countries.nigeria.detection import SETTINGS_FILE, load_settings
from src.evaluate_detection import (
    Suggestion,
    Tally,
    apply_suggestions,
    evaluate,
    format_breakdown,
    leading_digits,
    main,
    read_rows,
    suggest,
)

DATASET = load_datasets()["NGA"]
SETTINGS = load_settings()
GTBANK = "guaranty-trust-bank"
ZENITH = "zenith-bank"
OPAY = "opay-digital-services"
ACCESS = "access-bank"
# An active institution on NIP that account_detection.json says nothing about.
UNLISTED = next(
    bank["id"]
    for bank in DATASET.banks
    if bank["status"] == "active" and "nibss_code" in bank["identifiers"] and bank["id"] not in SETTINGS.institutions
)


def number_for(bank_id, serial):
    """An account number whose check digit is right for this bank: made up, not real."""
    return nuban.make_account_number(detection.institution_code(DATASET.banks_by_id[bank_id]), serial)


def synthetic_rows():
    """(account_number, nibss_code, bank_id) rows: 60 GTBank, 30 Zenith, 25 OPay, 5 Access, 2 unlisted, and 4 to skip."""
    rows = [(number_for(GTBANK, f"0{i:08d}"), "000013", "") for i in range(57)]
    # Three GTBank numbers outside its known leading digit, with the NIBSS code as a spreadsheet leaves it.
    rows += [(number_for(GTBANK, f"9{i:08d}"), "13", "") for i in range(3)]
    rows += [(number_for(ZENITH, f"{1 + i % 2}{i:08d}"), "", ZENITH) for i in range(30)]
    # OPay wallets: mobile numbers, plus a few NUBAN numbers under its code.
    rows += [(f"80{i:08d}", "100004", "") for i in range(20)]
    rows += [(number_for(OPAY, f"6{i:08d}"), "", OPAY) for i in range(5)]
    rows += [(number_for(ACCESS, f"0{i:08d}"), "", ACCESS) for i in range(5)]
    rows += [(number_for(UNLISTED, f"1{i:08d}"), "", UNLISTED) for i in range(2)]
    # Institutions the data file does not have, then account numbers that cannot be read.
    rows += [("0123456789", "999999", ""), ("0123456789", "", "no-such-bank")]
    rows += [("12345", "000013", ""), ("abc", "", ZENITH)]
    return rows


def write_csv(path, rows, header=("account_number", "nibss_code", "bank_id")):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


@pytest.fixture
def enquiries(tmp_path):
    path = tmp_path / "enquiries.csv"
    write_csv(path, synthetic_rows())
    return path


@pytest.fixture
def settings_copy(tmp_path):
    """A copy of the committed settings file with Windows line endings."""
    path = tmp_path / "account_detection.json"
    path.write_bytes(SETTINGS_FILE.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    return path


def tallies(path):
    evaluation = evaluate(DATASET, read_rows(path, DATASET).rows, SETTINGS)
    by_bank = {}
    for outcome in evaluation.outcomes:
        by_bank.setdefault(outcome.bank_id, []).append(outcome)
    return {bank_id: Tally.of(group) for bank_id, group in by_bank.items()}


class TestReading:
    def test_resolves_institutions_by_nibss_code_or_bank_id(self, enquiries):
        read = read_rows(enquiries, DATASET)
        assert Counter(row.bank_id for row in read.rows) == {GTBANK: 61, ZENITH: 31, OPAY: 25, ACCESS: 5, UNLISTED: 2}
        assert read.unknown_institutions == 2

    def test_a_bank_id_wins_over_a_nibss_code_and_headers_are_matched_loosely(self, tmp_path):
        path = tmp_path / "both.csv"
        write_csv(
            path,
            [("0123456789", "000013", ZENITH), ("0123456789", "000013", "")],
            (" Account_Number ", "NIBSS_CODE", "Bank_Id"),
        )
        assert [row.bank_id for row in read_rows(path, DATASET).rows] == [ZENITH, GTBANK]

    def test_refuses_a_file_without_the_columns_and_names_no_cell(self, tmp_path, capsys):
        path = tmp_path / "headerless.csv"
        path.write_text("0123456789,000013\n0123456780,000013\n", encoding="utf-8")
        with pytest.raises(SystemExit) as exit_info:
            main([str(path)])
        assert exit_info.value.code == 2
        err = capsys.readouterr().err
        assert "needs a header row with an account_number column" in err
        assert "0123456789" not in err
        half = tmp_path / "half.csv"
        write_csv(half, [("0123456789",)], ("account_number",))
        with pytest.raises(ValueError, match="nibss_code or bank_id"):
            read_rows(half, DATASET)

    def test_refuses_a_missing_file(self, tmp_path):
        with pytest.raises(SystemExit) as exit_info:
            main([str(tmp_path / "missing.csv")])
        assert exit_info.value.code == 2


class TestReport:
    def test_counts_evaluated_and_skipped_rows(self, enquiries, capsys):
        assert main([str(enquiries)]) == 0
        first_line = capsys.readouterr().out.splitlines()[0]
        assert first_line == (
            "Evaluated 122 of 126 rows in enquiries.csv: 2 named an institution that is not in the data file, "
            "2 had an account number that could not be read."
        )

    def test_never_prints_an_account_number(self, enquiries, capsys):
        main([str(enquiries)])
        out = capsys.readouterr().out
        assert re.search(r"[0-9]{10}", out) is None
        for account_number, _, _ in synthetic_rows():
            assert account_number not in out

    def test_scores_where_the_right_institution_ranked(self, enquiries):
        by_bank = tallies(enquiries)
        # Numbers made for GTBank that start with its known digit put it first; the three others still get recommended.
        assert by_bank[GTBANK].within[1] == 57
        assert by_bank[GTBANK].in_recommended == 60
        assert by_bank[GTBANK].missing == 0
        assert 1 < by_bank[GTBANK].mean_rank < 2
        assert by_bank[ZENITH].within == {1: 30, 3: 30}
        assert by_bank[ZENITH].mean_rank == 1
        # The 20 mobile numbers point to OPay first.
        assert by_bank[OPAY].within[1] >= 20
        assert by_bank[OPAY].rows == 25

    def test_prints_recall_and_rank_overall_and_per_institution_with_enough_rows(self, enquiries, capsys):
        main([str(enquiries)])
        out = capsys.readouterr().out
        assert re.search(r"top-1 recall +9\d\.\d%", out)
        assert re.search(r"top-3 recall +9\d\.\d%", out)
        assert re.search(r"recommended recall +9\d\.\d% +\(coverage 0\.9, \d\.\d candidates recommended on average\)", out)
        assert re.search(r"mean rank +1\.\d\d +\(the right institution is missing from the list in 0 rows, 0\.0%\)", out)
        breakdown = out[out.index("By institution") : out.index("Suggested settings")]
        assert "for the 3 with at least 20 rows" in breakdown
        assert re.search(rf"{GTBANK} +60 +95\.0% +95\.0% +100\.0% +1\.\d\d +0", breakdown)
        assert re.search(rf"{ZENITH} +30 +100\.0% +100\.0% +100\.0% +1\.00 +0", breakdown)
        assert OPAY in breakdown
        assert ACCESS not in breakdown
        assert UNLISTED not in breakdown

    def test_says_when_no_institution_has_enough_rows_for_a_breakdown(self, tmp_path):
        path = tmp_path / "few.csv"
        write_csv(path, [(number_for(GTBANK, f"0{i:08d}"), "000013", "") for i in range(5)])
        evaluation = evaluate(DATASET, read_rows(path, DATASET).rows, SETTINGS)
        assert format_breakdown(evaluation.outcomes).startswith("No institution has 20 rows or more")

    def test_nothing_to_evaluate_fails(self, tmp_path, capsys):
        path = tmp_path / "unknown.csv"
        write_csv(path, [("0123456789", "999999", ""), ("12345", "000013", "")])
        assert main([str(path)]) == 1
        out = capsys.readouterr().out
        assert out.startswith("Evaluated 0 of 2 rows")
        assert "Nothing to evaluate." in out

    def test_leaves_the_committed_settings_file_alone(self, enquiries):
        before = SETTINGS_FILE.read_bytes()
        main([str(enquiries)])
        assert SETTINGS_FILE.read_bytes() == before


class TestSuggestions:
    @pytest.fixture
    def suggestions(self, enquiries):
        evaluation = evaluate(DATASET, read_rows(enquiries, DATASET).rows, SETTINGS)
        return suggest(evaluation.outcomes, SETTINGS)

    def test_shares_are_percentages_of_rows_most_rows_first(self, suggestions):
        assert list(suggestions) == [GTBANK, ZENITH, OPAY, ACCESS, UNLISTED]
        assert {bank_id: item.share for bank_id, item in suggestions.items()} == {
            GTBANK: 49.2,
            ZENITH: 24.6,
            OPAY: 20.5,
            ACCESS: 4.1,
            UNLISTED: 1.64,
        }

    def test_prefixes_come_from_fifty_rows_at_least(self, suggestions):
        # 57 of GTBank's 60 numbers start with 0, exactly 95%, so the 9 is left out.
        assert suggestions[GTBANK].account_prefixes == ("0",)
        assert suggestions[ZENITH].account_prefixes is None
        # OPay's mobile numbers do not count, and five NUBAN numbers are too few.
        assert suggestions[OPAY].account_prefixes is None
        assert suggestions[ACCESS].account_prefixes is None

    def test_phone_number_fractions_only_for_institutions_that_issue_them(self, suggestions):
        assert suggestions[OPAY].phone_number_accounts == 0.8
        assert suggestions[GTBANK].phone_number_accounts is None
        assert suggestions[ACCESS].phone_number_accounts is None
        assert suggestions[UNLISTED].phone_number_accounts is None

    @pytest.mark.parametrize(
        "counts, expected",
        [
            ({"0": 57, "9": 3}, ("0",)),
            ({"0": 56, "9": 4}, ("0", "9")),
            ({"4": 30, "5": 30, "6": 30, "0": 1, "1": 1}, ("4", "5", "6")),
            ({digit: 10 for digit in "0123456789"}, ()),
            ({"1": 100}, ("1",)),
        ],
    )
    def test_leading_digits_cover_95_percent_of_the_numbers(self, counts, expected):
        assert leading_digits(Counter(counts)) == expected

    def test_prints_the_suggestions_as_json_ready_to_paste(self, enquiries, capsys, tmp_path):
        main([str(enquiries)])
        out = capsys.readouterr().out
        start = out.index("{\n", out.index("Suggested settings"))
        payload = json.loads(out[start : out.index("\n}\n", start) + 2])
        assert list(payload) == ["institutions"]
        assert payload["institutions"][GTBANK] == {"share": 49.2, "account_prefixes": ["0"]}
        assert payload["institutions"][OPAY] == {"share": 20.5, "phone_number_accounts": 0.8}
        assert payload["institutions"][UNLISTED] == {"share": 1.64}
        # Pasted over the committed institutions, the result is a valid settings file.
        raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        raw["institutions"] |= payload["institutions"]
        path = tmp_path / "pasted.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        assert load_settings(path).institutions[GTBANK].share == 49.2

    def test_a_suggestion_without_prefixes_or_phone_fraction_is_just_a_share(self):
        assert Suggestion(share=1.5, account_prefixes=None, phone_number_accounts=None).as_json() == {"share": 1.5}
        assert Suggestion(share=1.5, account_prefixes=(), phone_number_accounts=0.0).as_json() == {
            "share": 1.5,
            "phone_number_accounts": 0.0,
            "account_prefixes": [],
        }


class TestApply:
    def test_writes_the_suggestions_and_keeps_everything_else(self, enquiries, settings_copy, capsys):
        original = json.loads(settings_copy.read_text(encoding="utf-8"))
        assert main([str(enquiries), "--settings", str(settings_copy), "--apply"]) == 0
        assert "Wrote 5 institutions' settings" in capsys.readouterr().out
        written = json.loads(settings_copy.read_text(encoding="utf-8"))

        gtbank = written["institutions"][GTBANK]
        assert list(gtbank) == ["share", "account_prefixes", "aliases"]
        assert gtbank["share"] == 49.2
        assert gtbank["account_prefixes"] == ["0"]
        assert gtbank["aliases"] == original["institutions"][GTBANK]["aliases"]
        opay = written["institutions"][OPAY]
        assert (opay["share"], opay["phone_number_accounts"], opay["aliases"]) == (
            20.5,
            0.8,
            original["institutions"][OPAY]["aliases"],
        )
        # Too few Zenith rows to say anything about its leading digits, so the reviewed ones stay.
        zenith = written["institutions"][ZENITH]
        assert zenith["share"] == 24.6
        assert zenith["account_prefixes"] == original["institutions"][ZENITH]["account_prefixes"]
        assert written["institutions"][ACCESS]["aliases"] == original["institutions"][ACCESS]["aliases"]
        # An institution the file did not list is added at the end.
        assert list(written["institutions"])[-1] == UNLISTED
        assert written["institutions"][UNLISTED] == {"share": 1.64}
        # Everything the rows say nothing about is untouched.
        assert written["default_share_by_type"] == original["default_share_by_type"]
        for bank_id, item in original["institutions"].items():
            if bank_id not in (GTBANK, ZENITH, OPAY, ACCESS):
                assert written["institutions"][bank_id] == item, bank_id
        assert load_settings(settings_copy).institutions[GTBANK].account_prefixes == ("0",)

    def test_keeps_the_file_format_and_line_endings(self, settings_copy):
        before = settings_copy.read_bytes()
        assert apply_suggestions(settings_copy, {}) == (0, len(SETTINGS.institutions))
        assert settings_copy.read_bytes() == before
        apply_suggestions(settings_copy, {GTBANK: Suggestion(share=50.0, account_prefixes=("0",), phone_number_accounts=None)})
        after = settings_copy.read_bytes()
        assert after.count(b"\r\n") == after.count(b"\n")
        assert b'"share": 50.0' in after

    def test_removes_leading_digits_the_rows_contradict(self, settings_copy):
        assert "account_prefixes" in json.loads(settings_copy.read_text(encoding="utf-8"))["institutions"][ZENITH]
        changed, _ = apply_suggestions(
            settings_copy, {ZENITH: Suggestion(share=6.0, account_prefixes=(), phone_number_accounts=None)}
        )
        assert changed == 1
        zenith = json.loads(settings_copy.read_text(encoding="utf-8"))["institutions"][ZENITH]
        assert "account_prefixes" not in zenith
        assert zenith["aliases"]

    def test_counts_only_institutions_whose_settings_changed(self, settings_copy):
        current = SETTINGS.institutions[GTBANK]
        same = Suggestion(share=current.share, account_prefixes=current.account_prefixes, phone_number_accounts=None)
        assert apply_suggestions(settings_copy, {GTBANK: same}) == (0, len(SETTINGS.institutions) - 1)
