"""API keys for the hosted service, stored in SQLite as hashes.

A key is "bdk_" followed by 43 URL-safe characters (32 random bytes). Only its
SHA-256 hash is stored, so a copy of the database cannot be used to call the
API, and the key itself is shown once, when it is issued. Keys are long random
values rather than passwords, so a plain hash keeps them unrecoverable while
still allowing an indexed lookup on every request.

Each email address has at most one active key: issuing a new one revokes the
old one. Sign-up tokens, emailed to prove the address, are stored the same
way, expire after 30 minutes and work once.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

KEY_PREFIX = "bdk_"
DISPLAY_PREFIX_LENGTH = len(KEY_PREFIX) + 8
TOKEN_LIFETIME = timedelta(minutes=30)
LAST_USED_RESOLUTION = timedelta(hours=1)
_MAX_SECRET_LENGTH = 128
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY,
    key_hash TEXT NOT NULL UNIQUE,
    prefix TEXT NOT NULL,
    email TEXT NOT NULL,
    created_at TEXT NOT NULL,
    revoked_at TEXT,
    last_used_at TEXT
);
CREATE INDEX IF NOT EXISTS api_keys_email ON api_keys (email);
CREATE TABLE IF NOT EXISTS signup_tokens (
    token_hash TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT
);
"""


@dataclass(frozen=True)
class ApiKey:
    id: int
    prefix: str
    email: str
    created_at: str
    revoked_at: str | None
    last_used_at: str | None

    @property
    def active(self) -> bool:
        return self.revoked_at is None


def utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_email(value: object) -> str | None:
    """Return a lowercase, trimmed email address, or None if it does not look like one."""
    if not isinstance(value, str):
        return None
    email = value.strip().lower()
    return email if len(email) <= 254 and _EMAIL_PATTERN.match(email) else None


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class KeyStore:
    """Issue, check and revoke API keys and sign-up tokens in one SQLite file."""

    def __init__(self, path: str | Path, clock: Callable[[], datetime] = utc_now) -> None:
        self.path = str(path)
        self._clock = clock
        with closing(self._connect()) as db:
            db.executescript(_SCHEMA)

    def issue(self, email: str) -> tuple[str, ApiKey]:
        """Create a key for an email address, revoking any key it had. Returns the key and its record."""
        key = KEY_PREFIX + secrets.token_urlsafe(32)
        now = self._now()
        with self._transaction() as db:
            db.execute("UPDATE api_keys SET revoked_at = ? WHERE email = ? AND revoked_at IS NULL", (now, email))
            cursor = db.execute(
                "INSERT INTO api_keys (key_hash, prefix, email, created_at) VALUES (?, ?, ?, ?)",
                (hash_secret(key), key[:DISPLAY_PREFIX_LENGTH], email, now),
            )
            key_id = cursor.lastrowid
        return key, ApiKey(
            id=int(key_id or 0),
            prefix=key[:DISPLAY_PREFIX_LENGTH],
            email=email,
            created_at=now,
            revoked_at=None,
            last_used_at=None,
        )

    def authenticate(self, key: str) -> ApiKey | None:
        """Return the active key's record, or None for an unknown or revoked key."""
        if not key.startswith(KEY_PREFIX) or len(key) > _MAX_SECRET_LENGTH:
            return None
        with self._transaction() as db:
            row = db.execute("SELECT * FROM api_keys WHERE key_hash = ?", (hash_secret(key),)).fetchone()
            if row is None or row["revoked_at"] is not None:
                return None
            record = _record(row)
            now = self._clock()
            if record.last_used_at is None or datetime.fromisoformat(record.last_used_at) <= now - LAST_USED_RESOLUTION:
                db.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (self._now(), record.id))
        return record

    def revoke(self, key_id: int) -> bool:
        """Revoke a key by id. Returns False if it does not exist or was already revoked."""
        with self._transaction() as db:
            cursor = db.execute(
                "UPDATE api_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL", (self._now(), key_id)
            )
            return cursor.rowcount == 1

    def find(self, query: str = "") -> list[ApiKey]:
        """List keys whose email or display prefix contains the query, newest first."""
        pattern = f"%{query.strip().lower()}%"
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT * FROM api_keys WHERE lower(email) LIKE ? OR lower(prefix) LIKE ? ORDER BY id DESC",
                (pattern, pattern),
            ).fetchall()
        return [_record(row) for row in rows]

    def create_signup_token(self, email: str) -> str:
        """Create a one-time token that proves control of an email address."""
        token = secrets.token_urlsafe(32)
        now = self._clock()
        with self._transaction() as db:
            db.execute("DELETE FROM signup_tokens WHERE expires_at < ?", (_iso(now - timedelta(days=1)),))
            db.execute(
                "INSERT INTO signup_tokens (token_hash, email, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (hash_secret(token), email, _iso(now), _iso(now + TOKEN_LIFETIME)),
            )
        return token

    def signup_token_is_valid(self, token: str) -> bool:
        """Check a token without using it up."""
        if not token or len(token) > _MAX_SECRET_LENGTH:
            return False
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT 1 FROM signup_tokens WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?",
                (hash_secret(token), self._now()),
            ).fetchone()
        return row is not None

    def redeem_signup_token(self, token: str) -> str | None:
        """Use up a valid token and return its email address, or None if it is unknown, used or expired."""
        if not token or len(token) > _MAX_SECRET_LENGTH:
            return None
        now = self._now()
        with self._transaction() as db:
            row = db.execute(
                "SELECT email FROM signup_tokens WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?",
                (hash_secret(token), now),
            ).fetchone()
            if row is None:
                return None
            db.execute("UPDATE signup_tokens SET used_at = ? WHERE token_hash = ?", (now, hash_secret(token)))
        return str(row["email"])

    def _now(self) -> str:
        return _iso(self._clock())

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        """Run statements in one write transaction, so concurrent server processes cannot interleave."""
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).replace(microsecond=0).isoformat()


def _record(row: sqlite3.Row) -> ApiKey:
    return ApiKey(
        id=row["id"],
        prefix=row["prefix"],
        email=row["email"],
        created_at=row["created_at"],
        revoked_at=row["revoked_at"],
        last_used_at=row["last_used_at"],
    )
