"""Tests for storing and checking API keys and sign-up tokens."""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from src.core.api_keys import KEY_PREFIX, KeyStore, normalize_email


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    return KeyStore(tmp_path / "keys.sqlite3", clock=clock)


def every_stored_value(path):
    with sqlite3.connect(path) as db:
        return [
            str(value)
            for table in ("api_keys", "signup_tokens")
            for row in db.execute(f"SELECT * FROM {table}")  # noqa: S608 - fixed table names
            for value in row
        ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(" Ada@Example.COM ", "ada@example.com"), ("ada@example", None), ("not an email", None), ("", None), (None, None)],
)
def test_normalize_email(raw, expected):
    assert normalize_email(raw) == expected


class TestKeys:
    def test_issues_a_key_that_authenticates(self, store):
        key, record = store.issue("ada@example.com")
        assert key.startswith(KEY_PREFIX)
        assert len(key) == len(KEY_PREFIX) + 43
        assert record.prefix == key[:12]
        assert store.authenticate(key) == record

    def test_stores_only_a_hash_of_the_key(self, store, tmp_path):
        key, _ = store.issue("ada@example.com")
        assert not any(key in value for value in every_stored_value(tmp_path / "keys.sqlite3"))

    @pytest.mark.parametrize("attempt", ["", "bdk_wrong", "not-a-key", "bdk_" + "x" * 500])
    def test_rejects_unknown_keys(self, store, attempt):
        store.issue("ada@example.com")
        assert store.authenticate(attempt) is None

    def test_a_new_key_for_an_email_revokes_the_old_one(self, store):
        old_key, _ = store.issue("ada@example.com")
        new_key, _ = store.issue("ada@example.com")
        assert store.authenticate(old_key) is None
        assert store.authenticate(new_key) is not None

    def test_revoked_keys_stop_working(self, store):
        key, record = store.issue("ada@example.com")
        assert store.revoke(record.id) is True
        assert store.authenticate(key) is None
        assert store.revoke(record.id) is False

    def test_records_last_use_at_most_once_an_hour(self, store, clock):
        key, _ = store.issue("ada@example.com")
        store.authenticate(key)
        first = store.find("ada")[0].last_used_at
        clock.advance(minutes=30)
        store.authenticate(key)
        assert store.find("ada")[0].last_used_at == first
        clock.advance(minutes=31)
        store.authenticate(key)
        assert store.find("ada")[0].last_used_at == "2026-10-14T13:01:00+00:00"

    def test_finds_keys_by_email_or_prefix(self, store):
        _, ada = store.issue("ada@example.com")
        store.issue("grace@example.com")
        assert [key.email for key in store.find("ADA@")] == ["ada@example.com"]
        assert [key.id for key in store.find(ada.prefix)] == [ada.id]
        assert len(store.find()) == 2


class TestSignupTokens:
    def test_a_token_works_once(self, store):
        token = store.create_signup_token("ada@example.com")
        assert store.signup_token_is_valid(token)
        assert store.redeem_signup_token(token) == "ada@example.com"
        assert not store.signup_token_is_valid(token)
        assert store.redeem_signup_token(token) is None

    def test_tokens_expire_after_thirty_minutes(self, store, clock):
        token = store.create_signup_token("ada@example.com")
        clock.advance(minutes=31)
        assert not store.signup_token_is_valid(token)
        assert store.redeem_signup_token(token) is None

    @pytest.mark.parametrize("attempt", ["", "unknown-token", "x" * 500])
    def test_unknown_tokens_are_rejected(self, store, attempt):
        store.create_signup_token("ada@example.com")
        assert store.redeem_signup_token(attempt) is None
        assert not store.signup_token_is_valid(attempt)

    def test_counts_recent_tokens_per_email(self, store, clock):
        store.create_signup_token("ada@example.com")
        clock.advance(hours=12)
        store.create_signup_token("ada@example.com")
        store.create_signup_token("grace@example.com")
        assert store.signup_tokens_sent("ada@example.com", within=timedelta(days=1)) == 2
        assert store.signup_tokens_sent("ada@example.com", within=timedelta(hours=1)) == 1

    def test_stores_only_a_hash_of_the_token(self, store, tmp_path):
        token = store.create_signup_token("ada@example.com")
        assert not any(token in value for value in every_stored_value(tmp_path / "keys.sqlite3"))

    def test_old_used_up_tokens_are_cleared(self, store, clock, tmp_path):
        store.create_signup_token("ada@example.com")
        clock.advance(days=2)
        store.create_signup_token("grace@example.com")
        with sqlite3.connect(tmp_path / "keys.sqlite3") as db:
            assert [row[0] for row in db.execute("SELECT email FROM signup_tokens")] == ["grace@example.com"]
