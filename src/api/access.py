"""Rate limits for the hosted service.

Limits are off unless RATE_LIMIT_STORAGE_URI is set (see `src/core/settings.py`).
When on, every route under /api/ is limited per client: by IP address for
requests without an API key. Counters live in the configured store, usually
Redis, so every server process shares them. If the store is unreachable,
each process falls back to counting in memory rather than refusing requests.

Responses carry X-RateLimit-Limit, X-RateLimit-Remaining and X-RateLimit-Reset,
and a refused request gets a JSON 429 with Retry-After.
"""

from __future__ import annotations

from flask import Blueprint, Flask, current_app, jsonify, request
from flask_limiter import Limiter, RateLimitExceeded
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

from src.core.settings import Settings


def install_access_control(app: Flask, settings: Settings, limited: list[Blueprint]) -> Limiter:
    """Add rate limits to the given blueprints, and trust the configured number of proxies."""
    if settings.trusted_proxies:
        # Caddy and other proxies pass the client address in X-Forwarded-For.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=settings.trusted_proxies, x_proto=settings.trusted_proxies)  # type: ignore[method-assign]

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
    app.register_error_handler(RateLimitExceeded, rate_limited)
    return limiter


def rate_limit_key() -> str:
    """Count requests per client IP address."""
    return f"ip:{get_remote_address()}"


def api_rate_limit() -> str:
    return _settings().anonymous_rate_limit


def is_preflight() -> bool:
    """Browsers send OPTIONS before cross-site requests with custom headers; those are not counted."""
    return request.method == "OPTIONS"


def rate_limited(error: RateLimitExceeded):
    return jsonify({"success": False, "message": f"Rate limit exceeded: {error.description}. Try again later."}), 429


def _settings() -> Settings:
    return current_app.extensions["bank_settings"]
