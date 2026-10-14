"""Tests for the cleanup helpers shared by refresh modules."""

import pytest

from src.core.cleaning import clean_text, slugify


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Unity  Bank Plc", "Unity Bank Plc"),
        ("MOMO PAYMENT SERVICE BANK\r\n", "MOMO PAYMENT SERVICE BANK"),
        ("TAJ ", "TAJ"),
        ("  ", None),
        ("None", None),
        ("-", None),
        (None, None),
        (42, None),
    ],
)
def test_clean_text(raw, expected):
    assert clean_text(raw) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Access Bank Plc", "access-bank"),
        ("Citibank Nigeria Limited", "citibank-nigeria"),
        ("9 PSB Ltd", "9-psb"),
        ("Standard Chartered Bank Nigeria Ltd.", "standard-chartered-bank-nigeria"),
        (
            "Abubakar Tafawa Balewa University (ATBU) Microfinance Bank",
            "abubakar-tafawa-balewa-university-atbu-microfinance-bank",
        ),
        ("Société Générale", "societe-generale"),
        ("Opay Digital Services Limited (Formerly Paycom Nigeria Limited)", "opay-digital-services"),
        ("KongaPay Technologies Limited (Formerly Zinternet Limited )", "kongapay-technologies"),
        ("Funds And Electronic Transfer (FETS) Limited", "funds-and-electronic-transfer-fets"),
        ("Limited", "limited"),
        ("***", "bank"),
    ],
)
def test_slugify(name, expected):
    assert slugify(name) == expected
