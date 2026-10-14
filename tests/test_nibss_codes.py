"""Tests for matching CBN register banks to NIBSS institution codes."""

import pytest

from src.countries.nigeria.nibss_codes import assign_nibss_codes, match_key
from src.countries.nigeria.nip import NipInstitution as Nip


def bank(name, bank_type="microfinance", **identifiers):
    return {"name": name, "type": bank_type, "identifiers": dict(identifiers)}


def codes(banks):
    return {item["name"]: item["identifiers"].get("nibss_code") for item in banks}


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("Access Bank Plc", "access"),
        ("ACCESS(DIAMOND) BANK", "access diamond"),
        ("KUDA MFB", "kuda"),
        ("Kuda Micro-finance Bank Limited", "kuda"),
        ("Opay Digital Services Limited (Formerly Paycom Nigeria Limited)", "opay"),
        ("JIGAWA SAVINGS & LOANS", "jigawa savings loans"),
        ("Access Yello &amp; Beta", "access yello beta"),
    ],
)
def test_match_key(name, key):
    assert match_key(name) == key


def test_matches_names_that_reduce_to_the_same_words():
    banks = [bank("Access Bank Plc", "commercial"), bank("KUDA MFB"), bank("Opay Digital Services Limited", "mobile_money")]
    institutions = [
        Nip("000014", "ACCESS BANK"),
        Nip("000005", "ACCESS(DIAMOND) BANK"),
        Nip("090267", "KUDA MICROFINANCE BANK"),
        Nip("100004", "OPAY"),
    ]
    report = assign_nibss_codes(banks, institutions, {})
    assert codes(banks) == {"Access Bank Plc": "000014", "KUDA MFB": "090267", "Opay Digital Services Limited": "100004"}
    assert report.automatic == 3
    assert report.unmatched_banks == []
    assert report.unused_institutions == [Nip("000005", "ACCESS(DIAMOND) BANK")]


def test_records_every_match_with_the_nip_name_for_review():
    banks = [bank("KUDA MFB"), bank("Pagatech Limited", "mobile_money")]
    institutions = [Nip("090267", "KUDA MICROFINANCE BANK"), Nip("100002", "PAGA")]
    report = assign_nibss_codes(banks, institutions, {"Pagatech Limited": "100002"})
    assert report.matches == [
        ("KUDA MFB", "090267", "KUDA MICROFINANCE BANK", "automatic"),
        ("Pagatech Limited", "100002", "PAGA", "reviewed"),
    ]


def test_leaves_a_bank_unmatched_when_two_institutions_share_its_name():
    banks = [bank("Unity MFB")]
    report = assign_nibss_codes(banks, [Nip("090100", "UNITY MFB"), Nip("090200", "UNITY MICROFINANCE BANK")], {})
    assert codes(banks) == {"Unity MFB": None}
    assert report.unmatched_banks == ["Unity MFB"]


def test_leaves_both_banks_unmatched_when_they_claim_one_institution():
    banks = [bank("Unity MFB"), bank("UNITY MICROFINANCE BANK LIMITED")]
    assign_nibss_codes(banks, [Nip("090100", "UNITY MFB")], {})
    assert codes(banks) == {"Unity MFB": None, "UNITY MICROFINANCE BANK LIMITED": None}


def test_code_range_must_fit_the_bank_type():
    banks = [bank("Unity Bank Plc", "commercial")]
    assign_nibss_codes(banks, [Nip("090100", "UNITY BANK")], {})
    assert codes(banks) == {"Unity Bank Plc": None}


def test_type_words_must_agree():
    banks = [bank("Platinum Microfinance Bank Limited")]
    assign_nibss_codes(banks, [Nip("070013", "PLATINUM MORTGAGE BANK")], {})
    assert codes(banks) == {"Platinum Microfinance Bank Limited": None}


def test_reviewed_matches_win_over_the_rules():
    banks = [bank("Citibank Nigeria Limited", "commercial"), bank("Pagatech Limited", "mobile_money")]
    institutions = [Nip("000009", "CITI BANK"), Nip("100002", "PAGA")]
    report = assign_nibss_codes(banks, institutions, {"Citibank Nigeria Limited": "000009", "Pagatech Limited": "100002"})
    assert codes(banks) == {"Citibank Nigeria Limited": "000009", "Pagatech Limited": "100002"}
    assert report.reviewed == 2


def test_a_reviewed_null_keeps_a_bank_without_a_code():
    banks = [bank("KUDA MFB")]
    assign_nibss_codes(banks, [Nip("090267", "KUDA MICROFINANCE BANK")], {"KUDA MFB": None})
    assert codes(banks) == {"KUDA MFB": None}


def test_a_reviewed_code_is_never_given_to_another_bank_automatically():
    # Without the guard, the second bank would be the only automatic claimant of 070013.
    banks = [bank("PLATINUM MORTGAGE BANK", "mortgage"), bank("Platinum Mortgage Bank Limited", "mortgage")]
    assign_nibss_codes(banks, [Nip("070013", "PLATINUM MORTGAGE BANK")], {"PLATINUM MORTGAGE BANK": "070013"})
    assert codes(banks) == {"PLATINUM MORTGAGE BANK": "070013", "Platinum Mortgage Bank Limited": None}


def test_reports_reviewed_matches_that_no_longer_apply():
    banks = [bank("KUDA MFB")]
    report = assign_nibss_codes(banks, [Nip("090267", "KUDA MICROFINANCE BANK")], {"KUDA MFB": "090999", "Gone MFB": "090111"})
    assert codes(banks) == {"KUDA MFB": None}
    assert report.problems == [
        "Reviewed match for 'Gone MFB' names no bank in the register.",
        "Reviewed code 090999 for 'KUDA MFB' is not in the NIP list.",
    ]


def test_never_gives_one_code_to_two_banks():
    banks = [bank("KUDA MFB"), bank("Kuda Twin MFB")]
    report = assign_nibss_codes(banks, [Nip("090267", "KUDA MICROFINANCE BANK")], {"Kuda Twin MFB": "090267"})
    assert codes(banks) == {"KUDA MFB": None, "Kuda Twin MFB": "090267"}
    assert report.problems == []


def test_replaces_codes_from_an_earlier_refresh():
    banks = [bank("KUDA MFB", nibss_code="090111", cbn_institution_id="7")]
    assign_nibss_codes(banks, [Nip("090267", "KUDA MICROFINANCE BANK")], {})
    assert banks[0]["identifiers"] == {"cbn_institution_id": "7", "nibss_code": "090267"}


def test_reports_only_unused_institutions_of_types_in_scope():
    report = assign_nibss_codes([], [Nip("110002", "A PAYMENT PROCESSOR"), Nip("090300", "AN MFB")], {})
    assert report.unused_institutions == [Nip("090300", "AN MFB")]
