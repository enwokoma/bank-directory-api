"""Tests for the reviewed CBN bank codes and for applying them to register records."""

import json

import pytest

from src.core.dataset import DATA_DIR
from src.countries.nigeria.cbn_bank_codes import SCHEME, apply_cbn_bank_codes, load_cbn_bank_codes


def records(*names):
    return [
        {"name": name, "type": "commercial", "identifiers": {"cbn_institution_id": str(index)}}
        for index, name in enumerate(names, start=1)
    ]


def test_sets_the_code_on_every_bank_the_file_names():
    banks = records("Access Bank Plc", "Zenith Bank Plc", "New Bank")
    assert apply_cbn_bank_codes(banks, {"Access Bank Plc": "044", "Zenith Bank Plc": "057"}) == []
    assert [bank["identifiers"].get(SCHEME) for bank in banks] == ["044", "057", None]
    assert list(banks[0]["identifiers"]) == ["cbn_institution_id", SCHEME]


def test_reports_names_not_in_the_register():
    problems = apply_cbn_bank_codes(records("Access Bank Plc"), {"Access Bank Plc": "044", "Gone Bank": "999"})
    assert problems == ["CBN bank code for 'Gone Bank' names no bank in the register."]


def test_refuses_to_give_one_code_to_two_banks():
    banks = records("Wema Bank Plc", "ALAT by Wema")
    problems = apply_cbn_bank_codes(banks, {"Wema Bank Plc": "035", "ALAT by Wema": "035"})
    assert [bank["identifiers"].get(SCHEME) for bank in banks] == ["035", None]
    assert problems == [
        "CBN bank code 035 is given to both 'Wema Bank Plc' and 'ALAT by Wema'; 'ALAT by Wema' left without it."
    ]


def test_drops_a_code_the_file_no_longer_gives():
    banks = records("Old Bank")
    banks[0]["identifiers"][SCHEME] = "999"
    apply_cbn_bank_codes(banks, {})
    assert SCHEME not in banks[0]["identifiers"]


@pytest.mark.parametrize("content", [[], {"X": "12"}, {"X": 58}, {"X": "0058"}, {"X": "1234"}, {"X": None}])
def test_rejects_a_file_that_is_not_a_code_map(tmp_path, content):
    path = tmp_path / "cbn_bank_codes.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    with pytest.raises(ValueError, match="must map register names to 3- or 5-digit CBN bank codes"):
        load_cbn_bank_codes(path)


def test_committed_codes_match_the_data_file():
    """Every reviewed code names a bank in the data file, and the data file carries exactly those codes."""
    codes = load_cbn_bank_codes()
    dataset = json.loads((DATA_DIR / "NGA.json").read_text(encoding="utf-8"))
    in_file = {bank["name"]: bank["identifiers"][SCHEME] for bank in dataset["banks"] if SCHEME in bank["identifiers"]}
    assert in_file == codes
    assert len(set(codes.values())) == len(codes)


@pytest.mark.parametrize(
    "name, code",
    [
        ("Guaranty Trust Bank Plc", "058"),
        ("Access Bank Plc", "044"),
        ("Zenith Bank Plc", "057"),
        ("United Bank For Africa Plc", "033"),
        ("First Bank Nigeria Limited", "011"),
        ("Fidelity Bank Plc", "070"),
        ("First City Monument Bank Plc", "214"),
        ("Sterling Bank Plc", "232"),
        ("Wema Bank Plc", "035"),
        ("JAIZ BANK PLC", "301"),
        ("KUDA MFB", "50211"),
        ("Moniepoint MFB", "50515"),
    ],
)
def test_well_known_codes(name, code):
    assert load_cbn_bank_codes()[name] == code


def test_every_bank_on_nip_has_a_code_but_one():
    """Banks on NIP that the file leaves out fall back to their NIBSS code, so each omission is a deliberate choice."""
    dataset = json.loads((DATA_DIR / "NGA.json").read_text(encoding="utf-8"))
    without = [
        bank["name"]
        for bank in dataset["banks"]
        if bank["type"] in {"commercial", "merchant", "non_interest"}
        and "nibss_code" in bank["identifiers"]
        and SCHEME not in bank["identifiers"]
    ]
    assert without == ["QUEST MERCHANT BANK"]
