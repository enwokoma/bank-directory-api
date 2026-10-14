"""Tests for calling the API with an API key."""

import pytest

from app import create_app
from src.core.settings import Settings


@pytest.fixture
def app(tmp_path):
    settings = Settings(
        rate_limit_storage_uri="memory://",
        anonymous_rate_limit="2 per minute",
        key_rate_limit="4 per minute",
        api_key_database=str(tmp_path / "keys.sqlite3"),
    )
    app = create_app(settings)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def key(app):
    key, _ = app.extensions["bank_key_store"].issue("ada@example.com")
    return key


def get(client, path="/api/countries", ip="203.0.113.1", **headers):
    return client.get(path, headers=headers, environ_base={"REMOTE_ADDR": ip})


def test_a_key_gets_its_own_higher_limit(client, key):
    responses = [get(client, **{"X-API-Key": key}) for _ in range(5)]
    assert [response.status_code for response in responses] == [200, 200, 200, 200, 429]
    assert responses[0].headers["X-RateLimit-Limit"] == "4"


def test_a_key_is_also_accepted_as_a_bearer_token(client, key):
    assert get(client, Authorization=f"Bearer {key}").headers["X-RateLimit-Limit"] == "4"


def test_a_key_is_counted_apart_from_its_ip(client, key):
    for _ in range(2):
        get(client)
    assert get(client).status_code == 429
    assert get(client, **{"X-API-Key": key}).status_code == 200


def test_an_unknown_key_is_refused(client):
    response = get(client, **{"X-API-Key": "bdk_not-a-real-key"})
    assert response.status_code == 401
    assert response.get_json() == {"success": False, "message": "Invalid or revoked API key."}
    assert response.headers["WWW-Authenticate"].startswith("Bearer")


def test_requests_with_a_bad_key_still_count_against_the_ip(client):
    statuses = [get(client, **{"X-API-Key": "bdk_guess"}).status_code for _ in range(3)]
    assert statuses == [401, 401, 429]


def test_a_revoked_key_is_refused(app, client, key):
    store = app.extensions["bank_key_store"]
    store.revoke(store.find("ada")[0].id)
    assert get(client, **{"X-API-Key": key}).status_code == 401


@pytest.mark.parametrize("parameter", ["api_key", "apikey"])
def test_a_key_in_the_url_is_refused(client, key, parameter):
    response = client.get(f"/api/countries?{parameter}={key}")
    assert response.status_code == 400
    assert "X-API-Key header" in response.get_json()["message"]


def test_the_rate_limit_message_points_to_sign_up_when_it_is_available(tmp_path):
    settings = Settings(
        rate_limit_storage_uri="memory://",
        anonymous_rate_limit="1 per minute",
        api_key_database=str(tmp_path / "keys.sqlite3"),
        public_base_url="https://banks.example.test",
        signup_email_from="no-reply@example.test",
    )
    client = create_app(settings).test_client()
    get(client)
    assert "POST /api/keys/signup" in get(client).get_json()["message"]


def test_without_a_key_database_key_headers_are_ignored():
    client = create_app(Settings(rate_limit_storage_uri="memory://", anonymous_rate_limit="2 per minute")).test_client()
    response = get(client, **{"X-API-Key": "bdk_anything"})
    assert response.status_code == 200
    assert response.headers["X-RateLimit-Limit"] == "2"


class TestDescribeKey:
    def test_describes_the_callers_key(self, client, key):
        response = get(client, "/api/keys/me", **{"X-API-Key": key})
        body = response.get_json()
        assert response.status_code == 200
        assert body["key"]["prefix"] == key[:12]
        assert body["key"]["email"] == "ada@example.com"
        assert body["rate_limit"] == "4 per minute"
        assert response.headers["Cache-Control"] == "no-store"
        assert "ETag" not in response.headers

    def test_needs_a_key(self, client):
        response = get(client, "/api/keys/me")
        assert response.status_code == 401
        assert "X-API-Key header" in response.get_json()["message"]

    def test_does_not_exist_without_a_key_database(self):
        client = create_app(Settings()).test_client()
        assert client.get("/api/keys/me").status_code == 404
