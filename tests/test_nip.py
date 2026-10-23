"""Tests for reading the NIBSS Instant Payment institution list."""

import pytest

from src.core.source_client import SourceError
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
    def __init__(self, body, error=None):
        self.body = body
        self.error = error
        self.calls = []

    def get_json(self, url, params=None, headers=None):
        self.calls.append((url, headers))
        if self.error:
            raise self.error
        return self.body

    def post_json(self, url, data=None, headers=None):
        self.calls.append(("POST " + url, headers))
        return self.login_answer


class LoginClient(RecordingClient):
    def __init__(self, body, login_answer):
        super().__init__(body)
        self.login_answer = login_answer


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


def test_reads_paystack_nip_sort_codes():
    body = {
        "status": True,
        "message": "Banks retrieved",
        "data": [
            {"name": "Access Bank", "code": "044", "longcode": "044150149", "nip_sort_code": "000014"},
            {"name": "OPay Digital Services Limited (OPay)", "code": "999992", "nip_sort_code": "100004"},
            {"name": "Infinity trust  Mortgage Bank", "code": "070016", "nip_sort_code": None},
            {"name": "UNIABUJA MFB", "code": "51447", "nip_sort_code": "MFB51447"},
        ],
        "meta": None,
    }
    assert nip.parse_nip_institutions(body) == [
        nip.NipInstitution("000014", "Access Bank"),
        nip.NipInstitution("100004", "OPay Digital Services Limited (OPay)"),
    ]


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


def test_a_list_without_nibss_codes_reads_as_empty_for_nip_but_keeps_its_codes():
    """Flutterwave's list gives CBN bank codes only; the refresh gets nothing from it, the bank-code report does."""
    body = {
        "status": "success",
        "data": [{"id": 1, "code": "044", "name": "Access Bank"}, {"id": 2, "code": "50211", "name": "Kuda"}],
    }
    assert nip.parse_nip_institutions(body) == []
    assert nip.read_institution_list(body) == [
        nip.ListedInstitution("Access Bank", "044", None),
        nip.ListedInstitution("Kuda", "50211", None),
    ]


def test_reads_monnify_rows_with_the_nip_code_next_to_the_providers_code():
    body = {"responseBody": [{"name": "KUDA MFB", "code": "50211", "nipBankCode": "090267", "ussdTemplate": None}]}
    assert nip.read_institution_list(body) == [nip.ListedInstitution("KUDA MFB", "50211", "090267")]
    assert nip.parse_nip_institutions(body) == [nip.NipInstitution("090267", "KUDA MFB")]


class TestSettings:
    def test_not_configured_without_a_url(self):
        assert nip.settings_from_env({}) == []
        assert nip.settings_from_env({nip.ENV_URL: "  ", nip.ENV_API_KEY: "secret"}) == []

    def test_reads_url_key_and_default_header(self):
        settings = nip.settings_from_env({nip.ENV_URL: "https://example.test/banks", nip.ENV_API_KEY: "secret"})
        assert settings == [nip.NipSettings("https://example.test/banks", "secret", "X-API-Key")]

    def test_reads_a_login_url_and_labels_lists(self):
        settings = nip.settings_from_env(
            {
                nip.ENV_URL: "https://one.example.test/",
                nip.ENV_URL + "_4": "https://four.example.test/banks",
                nip.ENV_LOGIN_URL + "_4": "https://four.example.test/login",
                nip.ENV_API_KEY + "_4": "key:secret",
            }
        )
        assert settings[0].login_url is None
        assert settings[1].login_url == "https://four.example.test/login"
        assert [setting.label for setting in settings] == ["list 1", "list 4"]

    def test_header_can_be_changed(self):
        settings = nip.settings_from_env(
            {nip.ENV_URL: "https://example.test/banks", nip.ENV_API_KEY: "secret", nip.ENV_KEY_HEADER: "Authorization"}
        )
        assert settings[0].key_header == "Authorization"

    def test_reads_more_lists_from_numbered_settings(self):
        settings = nip.settings_from_env(
            {
                nip.ENV_URL: "https://one.example.test/",
                nip.ENV_URL + "_2": "https://two.example.test/",
                nip.ENV_API_KEY + "_2": "Bearer two",
                nip.ENV_KEY_HEADER + "_2": "Authorization",
                nip.ENV_URL + "_4": "https://four.example.test/",
                nip.ENV_URL + "_6": "https://ignored.example.test/",
            }
        )
        assert settings == [
            nip.NipSettings("https://one.example.test/", None, "X-API-Key"),
            nip.NipSettings("https://two.example.test/", "Bearer two", "Authorization", "NIP_INSTITUTIONS_URL_2"),
            nip.NipSettings("https://four.example.test/", None, "X-API-Key", "NIP_INSTITUTIONS_URL_4"),
        ]


def test_fetch_sends_the_key_in_the_configured_header():
    client = RecordingClient(ROWS)
    settings = nip.NipSettings("https://example.test/banks", "secret", "X-API-Key")
    assert nip.fetch_nip_institutions(client, settings) == EXPECTED
    assert client.calls == [("https://example.test/banks", {"X-API-Key": "secret"})]


def test_fetch_logs_in_first_when_the_list_has_a_login_url():
    client = LoginClient(ROWS, {"requestSuccessful": True, "responseBody": {"accessToken": "tok-123"}})
    settings = nip.NipSettings(
        "https://m.example.test/banks", "key:secret", "X-API-Key", "NIP_INSTITUTIONS_URL_4", "https://m.example.test/login"
    )
    assert nip.fetch_nip_institutions(client, settings) == EXPECTED
    assert client.calls == [
        ("POST https://m.example.test/login", {"Authorization": "Basic a2V5OnNlY3JldA=="}),
        ("https://m.example.test/banks", {"Authorization": "Bearer tok-123"}),
    ]


def test_a_login_needs_a_key_pair_and_a_token_in_the_answer():
    settings = nip.NipSettings(
        "https://m.example.test/banks", "lonely-key", "X-API-Key", "NIP_INSTITUTIONS_URL_4", "https://m.example.test/login"
    )
    with pytest.raises(ValueError, match="NIP_INSTITUTIONS_URL_4 needs a login, so its key must be 'api key:secret key'"):
        nip.fetch_nip_institutions(LoginClient(ROWS, {}), settings)
    paired = nip.NipSettings(
        "https://m.example.test/banks", "key:secret", "X-API-Key", "NIP_INSTITUTIONS_URL_4", "https://m.example.test/login"
    )
    with pytest.raises(ValueError, match="login for the list set in NIP_INSTITUTIONS_URL_4 returned no token"):
        nip.fetch_nip_institutions(LoginClient(ROWS, {"responseBody": {"accessToken": ""}}), settings=paired)


def test_fetch_without_a_key_sends_no_header():
    client = RecordingClient(ROWS)
    nip.fetch_nip_institutions(client, nip.NipSettings("https://example.test/banks", None, "X-API-Key"))
    assert client.calls == [("https://example.test/banks", None)]


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (
            SourceError("https://secret.example.test/banks answered 401", 401),
            "set in NIP_INSTITUTIONS_URL_2 answered HTTP 401.",
        ),
        (
            SourceError("https://secret.example.test/banks failed after 4 attempts: host secret.example.test"),
            "could not be reached.",
        ),
    ],
)
def test_errors_name_the_setting_not_the_endpoint(error, message):
    settings = nip.NipSettings("https://secret.example.test/banks", "key", "X-API-Key", "NIP_INSTITUTIONS_URL_2")
    with pytest.raises(SourceError) as raised:
        nip.fetch_nip_institutions(RecordingClient(None, error=error), settings)
    assert str(raised.value).endswith(message)
    assert "secret.example.test" not in str(raised.value)
    assert raised.value.__suppress_context__


def test_an_unreadable_list_names_the_setting():
    settings = nip.NipSettings("https://secret.example.test/banks", None, "X-API-Key", "NIP_INSTITUTIONS_URL_2")
    with pytest.raises(ValueError, match="set in NIP_INSTITUTIONS_URL_2: The institution list response has no"):
        nip.fetch_nip_institutions(RecordingClient({"message": "Unauthorized"}), settings)
