"""Tests for self-service API key sign-up."""

import re

import pytest
from botocore.exceptions import ClientError

from app import create_app
from src.core.settings import Settings


class FakeSender:
    def __init__(self, error=None):
        self.sent = []
        self.error = error

    def send(self, to, subject, text):
        if self.error:
            raise self.error
        self.sent.append((to, subject, text))

    def token(self):
        return re.search(r"/api/keys/verify\?token=(\S+)", self.sent[-1][2]).group(1)


def build(tmp_path, **overrides):
    values = {
        "rate_limit_storage_uri": "memory://",
        "signup_rate_limit": "20 per hour",
        "api_key_database": str(tmp_path / "keys.sqlite3"),
        "public_base_url": "https://banks.example.test",
        "signup_email_from": "no-reply@example.test",
    }
    settings = Settings(**{**values, **overrides})
    app = create_app(settings)
    app.config["TESTING"] = True
    sender = FakeSender()
    app.extensions["bank_email_sender"] = sender
    return app, app.test_client(), sender


@pytest.fixture
def setup(tmp_path):
    return build(tmp_path)


def sign_up(client, email="ada@example.com", ip="203.0.113.1"):
    return client.post("/api/keys/signup", json={"email": email}, environ_base={"REMOTE_ADDR": ip})


class TestSignup:
    def test_emails_a_one_time_link(self, setup):
        _, client, sender = setup
        response = sign_up(client, " Ada@Example.com ")
        assert response.status_code == 202
        assert response.get_json()["success"] is True
        assert response.headers["Cache-Control"] == "no-store"
        to, subject, text = sender.sent[0]
        assert (to, subject) == ("ada@example.com", "Your Bank Directory API key")
        assert "https://banks.example.test/api/keys/verify?token=" in text
        assert "within 30 minutes" in text

    def test_accepts_a_form_post_too(self, setup):
        _, client, sender = setup
        assert client.post("/api/keys/signup", data={"email": "ada@example.com"}).status_code == 202
        assert len(sender.sent) == 1

    @pytest.mark.parametrize("body", [{"email": "not-an-email"}, {"email": ""}, {}, {"email": 42}])
    def test_rejects_a_missing_or_invalid_address(self, setup, body):
        _, client, sender = setup
        response = client.post("/api/keys/signup", json=body)
        assert response.status_code == 400
        assert sender.sent == []

    def test_sends_at_most_three_links_a_day_but_answers_the_same(self, setup):
        _, client, sender = setup
        responses = [sign_up(client) for _ in range(5)]
        assert {response.status_code for response in responses} == {202}
        assert len({response.get_data() for response in responses}) == 1
        assert len(sender.sent) == 3

    def test_reports_an_email_failure_without_details(self, tmp_path):
        app, client, _ = build(tmp_path)
        error = ClientError({"Error": {"Code": "MessageRejected", "Message": "ada@example.com is not verified"}}, "SendEmail")
        app.extensions["bank_email_sender"] = FakeSender(error=error)
        response = sign_up(client)
        assert response.status_code == 503
        assert "ada@example.com" not in response.get_data(as_text=True)

    def test_sign_up_is_rate_limited_per_ip(self, tmp_path):
        _, client, _ = build(tmp_path, signup_rate_limit="2 per hour")
        statuses = [sign_up(client, f"user{number}@example.com").status_code for number in range(3)]
        assert statuses == [202, 202, 429]
        assert sign_up(client, "other@example.com", ip="203.0.113.9").status_code == 202


class TestVerify:
    def test_the_link_shows_a_button_without_using_up_the_token(self, setup):
        app, client, sender = setup
        sign_up(client)
        token = sender.token()
        for _ in range(2):
            page = client.get(f"/api/keys/verify?token={token}")
            assert page.status_code == 200
            assert '<form method="post" action="/api/keys/verify">' in page.get_data(as_text=True)
        assert app.extensions["bank_key_store"].signup_token_is_valid(token)

    def test_pages_carry_strict_security_headers(self, setup):
        _, client, sender = setup
        sign_up(client)
        page = client.get(f"/api/keys/verify?token={sender.token()}")
        assert page.headers["Content-Type"] == "text/html; charset=utf-8"
        assert page.headers["Cache-Control"] == "no-store"
        assert page.headers["Referrer-Policy"] == "no-referrer"
        assert "default-src 'none'" in page.headers["Content-Security-Policy"]

    def test_the_button_shows_a_working_key_once(self, setup):
        _, client, sender = setup
        sign_up(client)
        token = sender.token()
        page = client.post("/api/keys/verify", data={"token": token})
        key = re.search(r"<code>(bdk_[^<]+)</code>", page.get_data(as_text=True)).group(1)
        assert page.status_code == 200
        assert page.headers["Cache-Control"] == "no-store"
        assert client.get("/api/keys/me", headers={"X-API-Key": key}).get_json()["key"]["email"] == "ada@example.com"
        assert client.post("/api/keys/verify", data={"token": token}).status_code == 400

    def test_code_can_exchange_the_token_for_a_key_with_json(self, setup):
        _, client, sender = setup
        sign_up(client)
        response = client.post("/api/keys/verify", json={"token": sender.token()})
        body = response.get_json()
        assert response.status_code == 200
        assert body["api_key"].startswith("bdk_")
        assert body["prefix"] == body["api_key"][:12]

    def test_signing_up_again_replaces_the_old_key(self, setup):
        _, client, sender = setup
        sign_up(client)
        old_key = client.post("/api/keys/verify", json={"token": sender.token()}).get_json()["api_key"]
        sign_up(client)
        new_key = client.post("/api/keys/verify", json={"token": sender.token()}).get_json()["api_key"]
        assert client.get("/api/keys/me", headers={"X-API-Key": old_key}).status_code == 401
        assert client.get("/api/keys/me", headers={"X-API-Key": new_key}).status_code == 200

    @pytest.mark.parametrize("token", ["", "made-up", "<script>alert(1)</script>"])
    def test_an_unknown_token_is_refused(self, setup, token):
        _, client, _ = setup
        page = client.get("/api/keys/verify", query_string={"token": token})
        assert page.status_code == 400
        assert "<script>" not in page.get_data(as_text=True)
        assert client.post("/api/keys/verify", json={"token": token}).status_code == 400


def test_sign_up_does_not_exist_unless_configured(tmp_path):
    client = create_app(Settings(api_key_database=str(tmp_path / "keys.sqlite3"))).test_client()
    assert client.post("/api/keys/signup", json={"email": "ada@example.com"}).status_code == 404
    assert client.get("/api/keys/verify?token=x").status_code == 404
