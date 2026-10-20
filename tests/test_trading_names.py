"""Tests for applying reviewed trading names to register records."""

import json

import pytest

from src.core.trading_names import apply_trading_names, load_trading_names


def records(*names):
    return [{"name": name, "type": "microfinance", "identifiers": {}} for name in names]


def test_sets_a_trading_name_on_matching_banks_and_none_on_the_rest():
    banks = records("OSCT MFB", "KUDA MFB")
    assert apply_trading_names(banks, {"OSCT MFB": "OSCOTECH MFB"}) == []
    assert [bank["trading_name"] for bank in banks] == ["OSCOTECH MFB", None]


def test_reports_entries_that_name_no_bank():
    problems = apply_trading_names(records("KUDA MFB"), {"OSCT MFB": "OSCOTECH MFB"})
    assert problems == ["Trading name for 'OSCT MFB' names no bank in the register."]


def test_ignores_and_reports_a_trading_name_equal_to_the_register_name():
    banks = records("OSCOTECH MFB")
    problems = apply_trading_names(banks, {"OSCOTECH MFB": "OSCOTECH MFB"})
    assert banks[0]["trading_name"] is None
    assert problems == ["Trading name for 'OSCOTECH MFB' is the register name; the entry can be removed."]


@pytest.mark.parametrize("content", [[], {"OSCT MFB": None}, {"OSCT MFB": 1}])
def test_rejects_a_file_that_is_not_a_name_map(tmp_path, content):
    path = tmp_path / "trading_names.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    with pytest.raises(ValueError, match="must map register names to trading names"):
        load_trading_names(path)
