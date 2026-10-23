"""Routes for API key holders.

These exist only when API keys are enabled (API_KEY_DATABASE is set).
"""

from __future__ import annotations

from flask import Blueprint, abort, current_app, jsonify

from src.api.access import KEY_HEADER, current_caller

keys_bp = Blueprint("keys", __name__)


@keys_bp.before_request
def keys_enabled():
    if current_app.extensions.get("bank_key_store") is None:
        abort(404)


@keys_bp.route("/keys/me", methods=["GET"])
def describe_key():
    """
    Describe your API key
    ---
    tags: [API keys]
    parameters:
      - name: X-API-Key
        in: header
        type: string
        required: true
        description: Your API key
    responses:
      200:
        description: The key's prefix, email, dates and rate limit
        schema:
          $ref: '#/definitions/ApiKeyLookup'
      401:
        description: No key, or an unknown or revoked key
        schema:
          $ref: '#/definitions/Error'
    """
    key = current_caller().key
    if key is None:
        response = jsonify({"success": False, "message": f"Send your API key in the {KEY_HEADER} header."})
        response.headers["WWW-Authenticate"] = 'Bearer realm="bank-directory-api"'
        return response, 401
    settings = current_app.extensions["bank_settings"]
    response = jsonify(
        {
            "success": True,
            "key": {
                "prefix": key.prefix,
                "email": key.email,
                "created_at": key.created_at,
                "last_used_at": key.last_used_at,
            },
            "rate_limit": settings.key_rate_limit,
        }
    )
    # The response names the key's owner, so no cache may keep it.
    response.headers["Cache-Control"] = "no-store"
    return response, 200
