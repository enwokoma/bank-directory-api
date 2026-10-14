"""Tests for reading the NIBSS Instant Payment institution list."""

import pytest

from src.countries.nigeria import nip

ROWS = [
    {"code": "000014", "name": "ACCESS BANK"},
    {"code": "090267", "name": "KUDA MICROFINANCE BANK"},
    {"code": "100004", "name": "OPAY"},
]
EXPECTED = [
    nip.NipInstitution("000014", "ACCESS BANK"),
    nip.NipInstitution("090267", "KUDA MICROFINANCE BANK"),
    nip.NipInstitution("100004", "OPAY"),
]


class RecordingClient:
    def __init__(self, body):
        self.body = body
        self.calls = []

    def get_json(self, url, params=None, headers=None):
        self.calls.append((url, headers))
        return self.body


@pytest.mark.parametrize(
    "body",
    [
        ROWS,
        {"success": True, "data": ROWS},
        {"status": "00", "banks": ROWS},
        {"data": {"institutions": ROWS}},
    ],
)
def test_reads_common_response_shapes(body):
    assert nip.parse_nip_institutions(body) == EXPECTED


def test_reads_common_field_names():
    body = [{"bankCode": "000014", "bankName": " ACCESS  BANK "}, {"institutionCode": "090267", "institutionName": "KUDA"}]
    assert nip.parse_nip_institutions(body) == [
        nip.NipInstitution("000014", "ACCESS BANK"),
        nip.NipInstitution("090267", "KUDA"),
    ]


def test_prefers_a_nibss_code_over_an_api_specific_code():
    body = [{"code": "50211", "nibss_bank_code": "090267", "name": "Kuda Microfinance Bank"}]
    assert nip.parse_nip_institutions(body) == [nip.NipInstitution("090267", "Kuda Microfinance Bank")]


def test_an_empty_nibss_code_is_not_replaced_by_an_api_specific_code():
    body = [{"code": "100036", "nibss_bank_code": None, "name": "Some Wallet"}, {"code": "000014", "name": "ACCESS BANK"}]
    assert nip.parse_nip_institutions(body) == [nip.NipInstitution("000014", "ACCESS BANK")]


def test_skips_rows_without_a_six_digit_code_or_a_name():
    body = [
        {"code": "044", "name": "ACCESS"},
        {"code": "000014", "name": ""},
        {"code": "000015", "name": "ZENITH BANK"},
        "junk",
    ]
    assert nip.parse_nip_institutions(body) == [nip.NipInstitution("000015", "ZENITH BANK")]


@pytest.mark.parametrize("body", [[], {"data": []}, {"message": "Unauthorized"}, None])
def test_empty_or_unexpected_responses_stop_the_refresh(body):
    with pytest.raises(ValueError, match="no institutions"):
        nip.parse_nip_institutions(body)


class TestSettings:
    def test_not_configured_without_a_url(self):
        assert nip.settings_from_env({}) is None
        assert nip.settings_from_env({nip.ENV_URL: "  ", nip.ENV_API_KEY: "secret"}) is None

    def test_reads_url_key_and_default_header(self):
        settings = nip.settings_from_env({nip.ENV_URL: "https://example.test/banks", nip.ENV_API_KEY: "secret"})
        assert settings == nip.NipSettings("https://example.test/banks", "secret", "X-API-Key")

    def test_header_can_be_changed(self):
        settings = nip.settings_from_env(
            {nip.ENV_URL: "https://example.test/banks", nip.ENV_API_KEY: "secret", nip.ENV_KEY_HEADER: "Authorization"}
        )
        assert settings.key_header == "Authorization"


def test_fetch_sends_the_key_in_the_configured_header():
    client = RecordingClient(ROWS)
    settings = nip.NipSettings("https://example.test/banks", "secret", "X-API-Key")
    assert nip.fetch_nip_institutions(client, settings) == EXPECTED
    assert client.calls == [("https://example.test/banks", {"X-API-Key": "secret"})]


def test_fetch_without_a_key_sends_no_header():
    client = RecordingClient(ROWS)
    nip.fetch_nip_institutions(client, nip.NipSettings("https://example.test/banks", None, "X-API-Key"))
    assert client.calls == [("https://example.test/banks", None)]
