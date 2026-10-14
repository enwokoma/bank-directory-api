"""Rate limits and API keys for the hosted service.

Both are off unless configured (see `src/core/settings.py`). With
RATE_LIMIT_STORAGE_URI set, every limited route is counted per client: per
API key when the request carries a valid one, otherwise per IP address, each
with its own limits. Counters live in the configured store, usually Redis, so
every server process shares them; if the store is unreachable, each process
falls back to counting in memory rather than refusing requests.

With API_KEY_DATABASE set, a key may be sent in the X-API-Key header or as
"Authorization: Bearer <key>". An unknown or revoked key gets 401, and a key
in the URL gets 400, so keys stay out of access logs. Requests with a bad key
still count against their IP address, so keys cannot be guessed at speed.

Responses carry X-RateLimit-Limit, X-RateLimit-Remaining and X-RateLimit-Reset,
and a refused request gets a JSON 429 with Retry-After.
"""

from __future__ import annotations

from dataclasses import dataclass

from flask import Blueprint, Flask, current_app, g, jsonify, request
from flask_limiter import Limiter, RateLimitExceeded
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

from src.core.api_keys import ApiKey, KeyStore
from src.core.settings import Settings

KEY_HEADER = "X-API-Key"
_KEYS_IN_URL = ("api_key", "apikey")


@dataclass(frozen=True)
class Caller:
    """Who sent the request: the API key's record, or None for a request without a valid key."""

    key: ApiKey | None
    problem: tuple[int, str] | None = None


def install_access_control(app: Flask, settings: Settings, limited: list[Blueprint]) -> Limiter:
    """Add rate limits to the given blueprints, check API keys, and trust the configured proxies."""
    if settings.trusted_proxies:
        # Caddy and other proxies pass the client address in X-Forwarded-For.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=settings.trusted_proxies, x_proto=settings.trusted_proxies)  # type: ignore[method-assign]
    app.extensions["bank_key_store"] = KeyStore(settings.api_key_database) if settings.api_key_database else None

    limiter = Limiter(
        key_func=rate_limit_key,
        app=app,
        storage_uri=settings.rate_limit_storage_uri or "memory://",
        enabled=settings.rate_limits_enabled,
        headers_enabled=True,
        strategy="sliding-window-counter",
        key_prefix="bank-directory",
        swallow_errors=True,
        in_memory_fallback_enabled=True,
    )
    for blueprint in limited:
        limiter.limit(api_rate_limit, exempt_when=is_preflight)(blueprint)
    # Registered after the limiter, so a request with a bad key is counted before it is refused.
    app.before_request(refuse_bad_credentials)
    app.register_error_handler(RateLimitExceeded, rate_limited)
    return limiter


def current_caller() -> Caller:
    """Identify the request's sender once, and reuse the answer for limits and responses."""
    if "bank_caller" not in g:
        g.bank_caller = _identify()
    return g.bank_caller


def rate_limit_key() -> str:
    caller = current_caller()
    return f"key:{caller.key.id}" if caller.key else f"ip:{get_remote_address()}"


def api_rate_limit() -> str:
    settings = _settings()
    return settings.key_rate_limit if current_caller().key else settings.anonymous_rate_limit


def is_preflight() -> bool:
    """Browsers send OPTIONS before cross-site requests with custom headers; those are not counted."""
    return request.method == "OPTIONS"


def refuse_bad_credentials():
    if not request.path.startswith("/api/") or is_preflight():
        return None
    problem = current_caller().problem
    if problem is None:
        return None
    status, message = problem
    response = jsonify({"success": False, "message": message})
    if status == 401:
        response.headers["WWW-Authenticate"] = 'Bearer realm="bank-directory-api"'
    return response, status


def rate_limited(error: RateLimitExceeded):
    message = f"Rate limit exceeded: {error.description}. Try again later."
    if current_caller().key is None and _settings().signup_enabled:
        message += " An API key gives higher limits: POST /api/keys/signup."
    return jsonify({"success": False, "message": message}), 429


def _identify() -> Caller:
    if any(name in request.args for name in _KEYS_IN_URL):
        return Caller(None, (400, f"Send your API key in the {KEY_HEADER} header, not in the URL, so it stays out of logs."))
    key = request.headers.get(KEY_HEADER, "").strip()
    authorization = request.headers.get("Authorization", "")
    if not key and authorization[:7].lower() == "bearer ":
        key = authorization[7:].strip()
    store: KeyStore | None = current_app.extensions.get("bank_key_store")
    if not key or store is None:
        return Caller(None)
    record = store.authenticate(key)
    return Caller(record) if record else Caller(None, (401, "Invalid or revoked API key."))


def _settings() -> Settings:
    return current_app.extensions["bank_settings"]
