"""Tests that the Swagger spec describes every response, and that real answers match what it says.

Answers are validated against the schema the spec declares for their status, with every object
closed, so a field the spec forgets to mention fails the test as surely as a wrong type would.
"""

import json
import re

import jsonschema
import pytest
from botocore.exceptions import ClientError

from app import app, create_app
from src.api.schemas import DEFINITIONS
from src.core.settings import Settings

EXPECTED_DEFINITIONS = {
    "Error",
    "CountryReference",
    "CountrySummary",
    "CountryDetail",
    "CountryList",
    "CountryLookup",
    "BankType",
    "IdentifierScheme",
    "Source",
    "Bank",
    "BankList",
    "BankLookup",
    "DetectionCandidate",
    "Recommended",
    "Detection",
    "ApiKey",
    "ApiKeyLookup",
    "SignupReceipt",
    "IssuedApiKey",
}


class FakeSender:
    def __init__(self):
        self.sent = []
        self.error = None

    def send(self, to, subject, text):
        if self.error:
            raise self.error
        self.sent.append((to, subject, text))

    def token(self):
        return re.search(r"/api/keys/verify\?token=(\S+)", self.sent[-1][2]).group(1)


@pytest.fixture(scope="module")
def spec():
    app.config["TESTING"] = True
    return app.test_client().get("/apispec_1.json").get_json()


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


def hosted_app(tmp_path, **overrides):
    """An app with API keys and sign-up on, so the key routes answer, and a sender that keeps the emails."""
    settings = Settings(
        api_key_database=str(tmp_path / "keys.sqlite3"),
        public_base_url="https://banks.example.test",
        signup_email_from="no-reply@example.test",
        **overrides,
    )
    hosted = create_app(settings)
    hosted.config["TESTING"] = True
    sender = FakeSender()
    hosted.extensions["bank_email_sender"] = sender
    return hosted, hosted.test_client(), sender


def strict(schema):
    """The schema with every object closed to undeclared fields, and x-nullable turned into a null option."""
    if isinstance(schema, dict):
        closed = {key: strict(value) for key, value in schema.items()}
        if closed.get("type") == "object" and "properties" in closed:
            closed.setdefault("additionalProperties", False)
        if closed.pop("x-nullable", False):
            return {"anyOf": [closed, {"type": "null"}]}
        return closed
    if isinstance(schema, list):
        return [strict(item) for item in schema]
    return schema


def problems(spec, instance, name):
    """What is wrong with an answer according to one definition, with $refs resolved against the spec."""
    validator = jsonschema.Draft4Validator({"$ref": f"#/definitions/{name}", "definitions": strict(spec["definitions"])})
    return [
        f"{'/'.join(str(part) for part in error.absolute_path) or '.'}: {error.message}"
        for error in validator.iter_errors(instance)
    ]


def check(spec, response, method, path, status):
    """Check a real answer against the schema the spec declares for its status."""
    assert response.status_code == status, response.get_data(as_text=True)
    documented = spec["paths"][path][method]["responses"]
    assert str(status) in documented, f"{method.upper()} {path} does not document {status}"
    name = documented[str(status)]["schema"]["$ref"].rsplit("/", 1)[1]
    assert problems(spec, response.get_json(), name) == [], f"{method.upper()} {path} {status} is not a {name}"


class TestSpec:
    def test_defines_every_schema(self, spec):
        assert set(spec["definitions"]) == EXPECTED_DEFINITIONS
        assert spec["definitions"] == DEFINITIONS

    def test_every_documented_response_references_a_definition(self, spec):
        assert {"/api/keys/me", "/api/keys/signup", "/api/keys/verify"} <= set(spec["paths"])
        for path, methods in spec["paths"].items():
            for method, operation in methods.items():
                for status, response in operation["responses"].items():
                    where = f"{method.upper()} {path} {status}"
                    assert response["description"], where
                    reference = response.get("schema", {}).get("$ref", "")
                    assert reference.startswith("#/definitions/"), f"{where} has no schema"
                    assert reference.rsplit("/", 1)[1] in spec["definitions"], where

    def test_every_definition_is_referenced(self, spec):
        referenced = set(re.findall(r'"#/definitions/(\w+)"', json.dumps(spec)))
        assert referenced == set(spec["definitions"])

    def test_every_field_is_described_and_required(self, spec):
        for name, definition in spec["definitions"].items():
            assert definition["type"] == "object", name
            assert definition["description"], name
            assert definition["required"] == list(definition["properties"]), name
            for field, schema in definition["properties"].items():
                assert "$ref" in schema or schema["description"], f"{name}.{field}"

    @pytest.mark.parametrize("name", sorted(EXPECTED_DEFINITIONS))
    def test_each_example_matches_its_definition(self, spec, name):
        assert problems(spec, spec["definitions"][name]["example"], name) == []

    def test_the_examples_are_the_readme_ones(self, spec):
        assert spec["definitions"]["Bank"]["example"]["name"] == "Access Bank Plc"
        assert spec["definitions"]["BankList"]["example"]["banks"][0]["id"] == "zenith-bank"
        detection = spec["definitions"]["Detection"]["example"]
        assert detection["account_number"] == "0016563228"
        assert detection["best_guess"] == detection["candidates"][0]
        assert detection["recommended"]["candidates"] == detection["candidates"][:2]


PUBLIC_ANSWERS = [
    ("get", "/api/countries", "/api/countries", None, 200),
    ("get", "/api/countries/{country_code}", "/api/countries/NG", None, 200),
    ("get", "/api/countries/{country_code}", "/api/countries/XX", None, 404),
    ("get", "/api/countries/{country_code}/banks", "/api/countries/NG/banks?q=zenith", None, 200),
    ("get", "/api/countries/{country_code}/banks", "/api/countries/NG/banks?limit=5&offset=5", None, 200),
    ("get", "/api/countries/{country_code}/banks", "/api/countries/NG/banks?status=all&has=nibss_code", None, 200),
    ("get", "/api/countries/{country_code}/banks", "/api/countries/NG/banks?limit=0", None, 400),
    ("get", "/api/countries/{country_code}/banks", "/api/countries/NG/banks?has=swift", None, 400),
    ("get", "/api/countries/{country_code}/banks", "/api/countries/XX/banks", None, 404),
    ("get", "/api/countries/{country_code}/banks/{bank_id}", "/api/countries/NG/banks/access-bank", None, 200),
    ("get", "/api/countries/{country_code}/banks/{bank_id}", "/api/countries/NG/banks/no-such-bank", None, 404),
    ("get", "/api/detect-bank", "/api/detect-bank?account_number=0016563228", None, 200),
    ("get", "/api/detect-bank", "/api/detect-bank?account_number=0016563228&hint=GTBank&limit=1", None, 200),
    # A type no candidate belongs to: no best guess, nothing recommended.
    ("get", "/api/detect-bank", "/api/detect-bank?account_number=0016563228&type=merchant", None, 200),
    ("get", "/api/detect-bank", "/api/detect-bank?account_number=123", None, 400),
    ("get", "/api/detect-bank", "/api/detect-bank?account_number=0016563228&country=XX", None, 404),
    ("post", "/api/detect-bank", "/api/detect-bank", {"account_number": "0016563228", "limit": 3}, 200),
    ("post", "/api/detect-bank", "/api/detect-bank", {}, 400),
    (
        "get",
        "/api/countries/{country_code}/detect-bank",
        "/api/countries/NG/detect-bank?account_number=08012345678",
        None,
        200,
    ),
    (
        "get",
        "/api/countries/{country_code}/detect-bank",
        "/api/countries/XX/detect-bank?account_number=0016563228",
        None,
        404,
    ),
    (
        "post",
        "/api/countries/{country_code}/detect-bank",
        "/api/countries/NG/detect-bank",
        {"account_number": "0016563228", "coverage": 0.99},
        200,
    ),
    (
        "post",
        "/api/countries/{country_code}/detect-bank",
        "/api/countries/NG/detect-bank",
        {"account_number": "0016563228", "hint": "x" * 201},
        400,
    ),
]


class TestPublicAnswers:
    @pytest.mark.parametrize(
        "method, path, url, body, status",
        PUBLIC_ANSWERS,
        ids=[f"{method.upper()} {url} {status}" for method, _, url, _, status in PUBLIC_ANSWERS],
    )
    def test_the_answer_matches_the_schema_the_spec_declares(self, spec, client, method, path, url, body, status):
        response = client.get(url) if method == "get" else client.post(url, json=body)
        check(spec, response, method, path, status)

    def test_an_unknown_route_or_method_answers_with_an_error(self, spec, client):
        for response, status in ((client.get("/api/nothing-here"), 404), (client.post("/api/countries"), 405)):
            assert response.status_code == status
            assert problems(spec, response.get_json(), "Error") == []


class TestHostedAnswers:
    def test_describing_a_key(self, spec, tmp_path):
        hosted, client, _ = hosted_app(tmp_path)
        key, _ = hosted.extensions["bank_key_store"].issue("ada@example.com")
        # The first answer has no last_used_at yet; the second has the first call's.
        for _ in range(2):
            check(spec, client.get("/api/keys/me", headers={"X-API-Key": key}), "get", "/api/keys/me", 200)
        check(spec, client.get("/api/keys/me"), "get", "/api/keys/me", 401)
        check(spec, client.get("/api/keys/me", headers={"X-API-Key": "bdk_wrong"}), "get", "/api/keys/me", 401)

    def test_signing_up_and_getting_the_key(self, spec, tmp_path):
        _, client, sender = hosted_app(tmp_path)
        signup = {"email": "ada@example.com"}
        check(spec, client.post("/api/keys/signup", json=signup), "post", "/api/keys/signup", 202)
        check(spec, client.post("/api/keys/signup", json={}), "post", "/api/keys/signup", 400)
        token = sender.token()
        check(spec, client.post("/api/keys/verify", json={"token": token}), "post", "/api/keys/verify", 200)
        check(spec, client.post("/api/keys/verify", json={"token": token}), "post", "/api/keys/verify", 400)
        sender.error = ClientError({"Error": {"Code": "MessageRejected"}}, "SendEmail")
        check(spec, client.post("/api/keys/signup", json=signup), "post", "/api/keys/signup", 503)

    def test_too_many_sign_ups(self, spec, tmp_path):
        _, client, _ = hosted_app(tmp_path, rate_limit_storage_uri="memory://", signup_rate_limit="1 per minute")
        signup = {"email": "ada@example.com"}
        check(spec, client.post("/api/keys/signup", json=signup), "post", "/api/keys/signup", 202)
        check(spec, client.post("/api/keys/signup", json=signup), "post", "/api/keys/signup", 429)

    def test_refusals_on_any_route_are_errors_too(self, spec, tmp_path):
        """A bad key, a key in the URL and too many requests are refused on every route, in the Error shape."""
        _, client, _ = hosted_app(tmp_path, rate_limit_storage_uri="memory://", anonymous_rate_limit="2 per minute")
        refusals = [
            (client.get("/api/countries", headers={"X-API-Key": "bdk_wrong"}), 401),
            (client.get("/api/countries?api_key=bdk_wrong"), 400),
            (client.get("/api/countries"), 429),
        ]
        for response, status in refusals:
            assert response.status_code == status, response.get_data(as_text=True)
            assert problems(spec, response.get_json(), "Error") == []
