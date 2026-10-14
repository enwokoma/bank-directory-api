"""Settings for running the API, read from environment variables.

Everything is optional. With nothing set, the API serves its data openly with
no rate limits or keys, which is what a self-hosted copy usually wants. The
hosted service turns these on:

    RATE_LIMIT_STORAGE_URI  where rate limit counters live, for example redis://redis:6379/0
    ANONYMOUS_RATE_LIMIT    limits per client IP for requests without an API key
    KEY_RATE_LIMIT          limits per API key
    SIGNUP_RATE_LIMIT       limits per client IP for the API key sign-up endpoints
    API_KEY_DATABASE        SQLite file that holds API keys, stored only as hashes
    PUBLIC_BASE_URL         the API's public address, used in sign-up emails
    SIGNUP_EMAIL_FROM       sender of sign-up emails, sent through Amazon SES
    AWS_REGION              the Amazon SES region the sender is verified in
    TRUSTED_PROXIES         how many reverse proxies sit in front of the app

Limits use the `limits` library's notation, separated by semicolons, such as
"60 per hour;300 per day". Sign-up needs API_KEY_DATABASE, PUBLIC_BASE_URL and
SIGNUP_EMAIL_FROM. Amazon SES credentials come from the standard AWS sources,
such as an EC2 instance role. boto3 reads only AWS_DEFAULT_REGION by itself,
so AWS_REGION is read here and passed on; without it, boto3's own sources apply.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from limits import parse_many


@dataclass(frozen=True)
class Settings:
    rate_limit_storage_uri: str | None = None
    anonymous_rate_limit: str = "60 per hour;300 per day"
    key_rate_limit: str = "120 per minute;20000 per day"
    signup_rate_limit: str = "10 per hour;30 per day"
    api_key_database: str | None = None
    public_base_url: str | None = None
    signup_email_from: str | None = None
    aws_region: str | None = None
    trusted_proxies: int = 0

    @property
    def rate_limits_enabled(self) -> bool:
        return bool(self.rate_limit_storage_uri)

    @property
    def api_keys_enabled(self) -> bool:
        return bool(self.api_key_database)

    @property
    def signup_enabled(self) -> bool:
        return self.api_keys_enabled and bool(self.public_base_url) and bool(self.signup_email_from)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ) -> Settings:
        """Read settings from the environment, rejecting values that would misbehave at runtime."""
        defaults = cls()

        def text(name: str) -> str | None:
            return (environ.get(name) or "").strip() or None

        def limit(name: str, default: str) -> str:
            value = text(name) or default
            try:
                parse_many(value)
            except ValueError as exc:
                raise ValueError(f"{name} is not a valid rate limit: {value!r}") from exc
            return value

        proxies = text("TRUSTED_PROXIES") or "0"
        if not proxies.isdigit():
            raise ValueError(f"TRUSTED_PROXIES must be a whole number, not {proxies!r}")
        base_url = text("PUBLIC_BASE_URL")
        if base_url and not base_url.startswith(("https://", "http://")):
            raise ValueError(f"PUBLIC_BASE_URL must start with https://, not {base_url!r}")

        return cls(
            rate_limit_storage_uri=text("RATE_LIMIT_STORAGE_URI"),
            anonymous_rate_limit=limit("ANONYMOUS_RATE_LIMIT", defaults.anonymous_rate_limit),
            key_rate_limit=limit("KEY_RATE_LIMIT", defaults.key_rate_limit),
            signup_rate_limit=limit("SIGNUP_RATE_LIMIT", defaults.signup_rate_limit),
            api_key_database=text("API_KEY_DATABASE"),
            public_base_url=base_url.rstrip("/") if base_url else None,
            signup_email_from=text("SIGNUP_EMAIL_FROM"),
            aws_region=text("AWS_REGION"),
            trusted_proxies=int(proxies),
        )
