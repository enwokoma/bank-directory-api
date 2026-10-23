"""Tests for reading the configured institution lists and reporting what they add to the CBN bank codes."""

import base64

import pytest

from src.core.source_client import SourceError
from src.countries.nigeria import bank_code_sources as sources
from src.countries.nigeria import nip
from src.countries.nigeria.bank_code_sources import ProviderCode, collect, report

PAYSTACK = "https://paystack.example.test/bank"
MONNIFY_LOGIN = "https://monnify.example.test/login"
MONNIFY = "https://monnify.example.test/banks"
FLUTTERWAVE = "https://flutterwave.example.test/banks/NG"


class FakeClient:
    """Answer each endpoint with a canned body, and remember the headers sent."""

    def __init__(self, answers, failures=()):
        self.answers = answers
        self.failures = set(failures)
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info):
        return None

    def get_json(self, url, params=None, headers=None):
        return self._answer(url, headers)

    def post_json(self, url, data=None, headers=None):
        return self._answer(url, headers)

    def _answer(self, url, headers):
        if url in self.failures:
            raise SourceError(f"{url} answered 504", 504)
        self.headers[url] = headers
        return self.answers[url]


ANSWERS = {
    PAYSTACK: {"data": [{"name": "Kuda Bank", "code": "50211", "nip_sort_code": "090267"}]},
    MONNIFY_LOGIN: {"requestSuccessful": True, "responseBody": {"accessToken": "monnify-token"}},
    MONNIFY: {"responseBody": [{"name": "KUDA MFB", "code": "50211", "nipBankCode": "090267"}]},
    FLUTTERWAVE: {"status": "success", "data": [{"id": 1, "name": "Kuda Microfinance Bank", "code": "50211"}]},
}
SETTINGS = {
    nip.ENV_URL + "_3": PAYSTACK,
    nip.ENV_URL + "_4": MONNIFY,
    nip.ENV_LOGIN_URL + "_4": MONNIFY_LOGIN,
    nip.ENV_API_KEY + "_4": "key:secret",
    nip.ENV_URL + "_5": FLUTTERWAVE,
    nip.ENV_API_KEY + "_5": "Bearer flw-secret",
    nip.ENV_KEY_HEADER + "_5": "Authorization",
}


def bank(bank_id, name, nibss_code, cbn_bank_code=None):
    identifiers = {"nibss_code": nibss_code}
    if cbn_bank_code:
        identifiers["cbn_bank_code"] = cbn_bank_code
    return {
        "id": bank_id,
        "name": name,
        "trading_name": name,
        "type": "microfinance",
        "status": "active",
        "identifiers": identifiers,
    }


def test_reads_every_configured_list_with_its_own_login():
    client = FakeClient(ANSWERS)
    codes, notes = collect(client, SETTINGS)
    assert [(code.provider, code.code, code.nibss_code) for code in codes] == [
        ("list 3", "50211", "090267"),
        ("list 4", "50211", "090267"),
        ("list 5", "50211", None),
    ]
    assert notes == [
        "list 3 (NIP_INSTITUTIONS_URL_3) names 1 institutions.",
        "list 4 (NIP_INSTITUTIONS_URL_4) names 1 institutions.",
        "list 5 (NIP_INSTITUTIONS_URL_5) names 1 institutions.",
    ]
    basic = base64.b64encode(b"key:secret").decode()
    assert client.headers[MONNIFY_LOGIN] == {"Authorization": f"Basic {basic}"}
    assert client.headers[MONNIFY] == {"Authorization": "Bearer monnify-token"}
    assert client.headers[FLUTTERWAVE] == {"Authorization": "Bearer flw-secret"}


def test_skips_a_list_that_cannot_be_read_and_says_when_none_is_set():
    client = FakeClient(ANSWERS, failures={FLUTTERWAVE})
    codes, notes = collect(client, {k: v for k, v in SETTINGS.items() if not k.endswith("_4")})
    assert [code.provider for code in codes] == ["list 3"]
    assert notes == [
        "list 3 (NIP_INSTITUTIONS_URL_3) names 1 institutions.",
        "list 5 skipped: The institution list set in NIP_INSTITUTIONS_URL_5 answered HTTP 504.",
    ]
    assert collect(client, {}) == ([], ["No institution list is set: see NIP_INSTITUTIONS_URL in .env.example."])


def test_a_login_without_a_token_is_reported_not_raised():
    answers = {**ANSWERS, MONNIFY_LOGIN: {"responseBody": {}}}
    _, notes = collect(FakeClient(answers), {k: v for k, v in SETTINGS.items() if k.endswith("_4")})
    assert notes == ["list 4 skipped: The login for the list set in NIP_INSTITUTIONS_URL_4 returned no token."]


def test_report_lists_missing_disagreeing_and_confirmed_codes():
    banks = [
        bank("kuda-mfb", "KUDA MFB", "090267", "50211"),
        bank("accion-microfinance-bank", "Accion Microfinance Bank Limited", "090134", "50009"),
        bank("new-mfb", "New Microfinance Bank", "090999"),
        bank("quiet-mfb", "Quiet Microfinance Bank", "090998"),
    ]
    codes = [
        ProviderCode("list 3", "Kuda Bank", "50211", "090267"),
        ProviderCode("list 4", "KUDA MFB", "090267", "090267"),  # the NIBSS code itself: not a CBN code
        ProviderCode("list 3", "Accion Microfinance Bank", "602", "090134"),
        ProviderCode("list 4", "New MFB", "51999", "090999"),
        ProviderCode("list 5", "New Microfinance Bank", "51999"),  # matched by name, no NIBSS code
        ProviderCode("list 5", "Optimus Bank", "00107"),  # padded 3-digit code, for a bank not in the list
    ]
    assert report(banks, codes) == [
        "1 institutions without a reviewed CBN bank code that a list gives a code:",
        "  090999 New Microfinance Bank: 51999 (list 4, list 5)",
        "1 reviewed codes a list disagrees with (3-digit codes are often legacy NIBSS codes):",
        "  090134 Accion Microfinance Bank Limited: reviewed 50009; 602 (list 3)",
        "1 reviewed codes every list that names the bank confirms.",
    ]


@pytest.mark.parametrize(
    "value, expected",
    [("058", "058"), ("50515", "50515"), ("00107", "107"), ("090267", None), ("035A", "035"), ("D53", None), ("5129", None)],
)
def test_cbn_style_codes(value, expected):
    assert sources._cbn_style(value) == expected


def test_main_prints_the_report(tmp_path, monkeypatch, capsys):
    data_dir = tmp_path / "countries"
    data_dir.mkdir()
    (data_dir / "NGA.json").write_text(
        '{"country": "NGA", "retrieved_on": "2026-10-22", "sources": [], "banks": '
        '[{"id": "kuda-mfb", "name": "KUDA MFB", "trading_name": "KUDA MFB", "type": "microfinance", "status": "active", '
        '"identifiers": {"nibss_code": "090267"}}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(sources, "SourceClient", lambda: FakeClient(ANSWERS))
    monkeypatch.setattr(sources, "ENV_FILE", tmp_path / "no.env")
    monkeypatch.setenv(nip.ENV_URL + "_3", PAYSTACK)
    assert sources.main(["--data-dir", str(data_dir)]) == 0
    out = capsys.readouterr().out
    assert "list 3 (NIP_INSTITUTIONS_URL_3) names 1 institutions." in out
    assert "  090267 KUDA MFB: 50211 (list 3)" in out
