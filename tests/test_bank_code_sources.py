"""Tests for reading payment providers' bank lists and reporting what they add to the CBN bank codes."""

import base64

import pytest

from src.core.source_client import SourceError
from src.countries.nigeria import bank_code_sources as sources
from src.countries.nigeria.bank_code_sources import ProviderCode, collect, report


class FakeClient:
    """Answer each provider endpoint with a canned body, and remember the headers sent."""

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
    sources.PAYSTACK_URL: {"data": [{"name": "Kuda Bank", "code": "50211", "nip_sort_code": "090267"}]},
    sources.MONNIFY_LOGIN_URL: {"responseBody": {"accessToken": "monnify-token"}},
    sources.MONNIFY_BANKS_URL: {"responseBody": [{"name": "KUDA MFB", "code": "50211", "nipBankCode": "090267"}]},
    sources.FLUTTERWAVE_TOKEN_URL: {"access_token": "flw-token"},
    sources.FLUTTERWAVE_BANKS_URL: {"data": [{"name": "Kuda Microfinance Bank", "code": "50211"}]},
}
CREDENTIALS = {
    "MONNIFY_API_KEY": "key",
    "MONNIFY_SECRET_KEY": "secret",
    "FLUTTERWAVE_CLIENT_ID": "id",
    "FLUTTERWAVE_CLIENT_SECRET": "secret",
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


def test_reads_every_provider_with_its_own_login():
    client = FakeClient(ANSWERS)
    codes, notes = collect(client, CREDENTIALS)
    assert [(code.provider, code.code, code.nibss_code) for code in codes] == [
        ("paystack", "50211", "090267"),
        ("monnify", "50211", "090267"),
        ("flutterwave", "50211", None),
    ]
    assert notes == ["Paystack lists 1 institutions.", "Monnify lists 1 institutions.", "Flutterwave lists 1 institutions."]
    basic = base64.b64encode(b"key:secret").decode()
    assert client.headers[sources.MONNIFY_LOGIN_URL] == {"Authorization": f"Basic {basic}"}
    assert client.headers[sources.MONNIFY_BANKS_URL] == {"Authorization": "Bearer monnify-token"}
    assert client.headers[sources.FLUTTERWAVE_BANKS_URL] == {"Authorization": "Bearer flw-token"}


def test_skips_providers_without_credentials_or_that_fail():
    client = FakeClient(ANSWERS, failures={sources.FLUTTERWAVE_BANKS_URL})
    codes, notes = collect(client, {**CREDENTIALS, "MONNIFY_API_KEY": ""})
    assert [code.provider for code in codes] == ["paystack"]
    assert notes == [
        "Monnify skipped: MONNIFY_API_KEY and MONNIFY_SECRET_KEY are not set.",
        "Paystack lists 1 institutions.",
        f"Flutterwave skipped: {sources.FLUTTERWAVE_BANKS_URL} answered 504",
    ]


def test_a_login_without_a_token_is_reported_not_raised():
    answers = {**ANSWERS, sources.MONNIFY_LOGIN_URL: {"responseBody": {}}}
    _, notes = collect(FakeClient(answers), {**CREDENTIALS, "FLUTTERWAVE_CLIENT_ID": ""})
    assert "Monnify skipped: Monnify's login answer has no access token." in notes


def test_report_lists_missing_disagreeing_and_confirmed_codes():
    banks = [
        bank("kuda-mfb", "KUDA MFB", "090267", "50211"),
        bank("accion-microfinance-bank", "Accion Microfinance Bank Limited", "090134", "50009"),
        bank("new-mfb", "New Microfinance Bank", "090999"),
        bank("quiet-mfb", "Quiet Microfinance Bank", "090998"),
    ]
    codes = [
        ProviderCode("paystack", "Kuda Bank", "50211", "090267"),
        ProviderCode("monnify", "KUDA MFB", "090267", "090267"),  # the NIBSS code itself: not a CBN code
        ProviderCode("paystack", "Accion Microfinance Bank", "602", "090134"),
        ProviderCode("monnify", "New MFB", "51999", "090999"),
        ProviderCode("flutterwave", "New Microfinance Bank", "51999"),  # matched by name, no NIBSS code
        ProviderCode("flutterwave", "Optimus Bank", "00107"),  # padded 3-digit code, for a bank not in the list
    ]
    lines = report(banks, codes)
    assert lines == [
        "1 institutions without a reviewed CBN bank code that a provider gives a code:",
        "  090999 New Microfinance Bank: 51999 (flutterwave, monnify)",
        "1 reviewed codes a provider disagrees with (3-digit codes are often legacy NIBSS codes):",
        "  090134 Accion Microfinance Bank Limited: reviewed 50009; 602 (paystack)",
        "1 reviewed codes every provider that lists the bank confirms.",
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
    for name in CREDENTIALS:
        monkeypatch.delenv(name, raising=False)
    assert sources.main(["--data-dir", str(data_dir)]) == 0
    out = capsys.readouterr().out
    assert "Paystack lists 1 institutions." in out
    assert "Monnify skipped" in out
    assert "  090267 KUDA MFB: 50211 (paystack)" in out
