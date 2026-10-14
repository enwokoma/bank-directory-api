"""Tests for reading the API's settings from the environment."""

import pytest

from src.core.settings import Settings


def test_nothing_set_means_an_open_api():
    settings = Settings.from_env({})
    assert settings == Settings()
    assert not settings.rate_limits_enabled
    assert not settings.api_keys_enabled
    assert not settings.signup_enabled


def test_reads_the_hosted_settings():
    settings = Settings.from_env(
        {
            "RATE_LIMIT_STORAGE_URI": "redis://redis:6379/0",
            "ANONYMOUS_RATE_LIMIT": "10 per minute",
            "KEY_RATE_LIMIT": "100 per minute;5000 per day",
            "SIGNUP_RATE_LIMIT": "3 per hour",
            "API_KEY_DATABASE": "/data/keys.sqlite3",
            "PUBLIC_BASE_URL": "https://banks.example.test/",
            "SIGNUP_EMAIL_FROM": "Bank Directory API <no-reply@example.test>",
            "TRUSTED_PROXIES": "1",
        }
    )
    assert settings == Settings(
        rate_limit_storage_uri="redis://redis:6379/0",
        anonymous_rate_limit="10 per minute",
        key_rate_limit="100 per minute;5000 per day",
        signup_rate_limit="3 per hour",
        api_key_database="/data/keys.sqlite3",
        public_base_url="https://banks.example.test",
        signup_email_from="Bank Directory API <no-reply@example.test>",
        trusted_proxies=1,
    )
    assert settings.rate_limits_enabled and settings.api_keys_enabled and settings.signup_enabled


def test_sign_up_needs_the_key_database_base_url_and_sender():
    assert not Settings(api_key_database="keys.sqlite3", public_base_url="https://x.test").signup_enabled
    assert not Settings(public_base_url="https://x.test", signup_email_from="a@x.test").signup_enabled


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("ANONYMOUS_RATE_LIMIT", "lots", "ANONYMOUS_RATE_LIMIT is not a valid rate limit"),
        ("KEY_RATE_LIMIT", "100 per fortnight", "KEY_RATE_LIMIT is not a valid rate limit"),
        ("TRUSTED_PROXIES", "one", "TRUSTED_PROXIES must be a whole number"),
        ("PUBLIC_BASE_URL", "banks.example.test", "PUBLIC_BASE_URL must start with https://"),
    ],
)
def test_rejects_settings_that_would_misbehave(name, value, message):
    with pytest.raises(ValueError, match=message):
        Settings.from_env({name: value})
