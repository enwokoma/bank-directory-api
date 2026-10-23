"""Self-service API key sign-up, proved by email.

1. POST /api/keys/signup with an email address. The answer is the same
   whether or not the address already has a key, so nobody can test which
   addresses do. Each address gets at most three links a day; a link whose
   email could not be sent does not count.
2. The email links to GET /api/keys/verify?token=..., which only shows a
   button. Mail scanners that open links therefore cannot use up the token.
3. The button posts to /api/keys/verify, which uses up the token and shows the
   key once. Any earlier key for that address stops working.

Code can do the last step with JSON instead: POST {"token": "..."}.
These routes exist only when sign-up is configured (see src/core/settings.py).
"""

from __future__ import annotations

import html
import logging
from datetime import timedelta
from urllib.parse import quote

from botocore.exceptions import BotoCoreError, ClientError
from flask import Blueprint, abort, current_app, jsonify, request

from src.api.access import KEY_HEADER
from src.core.api_keys import TOKEN_LIFETIME, KeyStore, normalize_email
from src.core.email import EmailSender

logger = logging.getLogger(__name__)

signup_bp = Blueprint("signup", __name__)

LINKS_PER_EMAIL_PER_DAY = 3
_NO_STORE = {"Cache-Control": "no-store"}
_PAGE_HEADERS = {
    **_NO_STORE,
    "Content-Type": "text/html; charset=utf-8",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


@signup_bp.before_request
def signup_enabled():
    if not current_app.extensions["bank_settings"].signup_enabled:
        abort(404)


@signup_bp.route("/keys/signup", methods=["POST"])
def signup():
    """
    Ask for an API key
    ---
    tags: [API keys]
    consumes: [application/json]
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [email]
          properties:
            email:
              type: string
              example: you@example.com
    responses:
      202:
        description: A link to get the key is emailed, if the address can receive it
        schema:
          $ref: '#/definitions/SignupReceipt'
      400:
        description: The email address is missing or invalid
        schema:
          $ref: '#/definitions/Error'
      429:
        description: Too many sign-ups from this IP address
        schema:
          $ref: '#/definitions/Error'
      503:
        description: The email could not be sent
        schema:
          $ref: '#/definitions/Error'
    """
    email = normalize_email(_field("email"))
    if email is None:
        return jsonify({"success": False, "message": "Send a valid email address as `email`."}), 400, _NO_STORE

    store = _store()
    if store.signup_tokens_sent(email, within=timedelta(days=1)) < LINKS_PER_EMAIL_PER_DAY:
        token = store.create_signup_token(email)
        try:
            _sender().send(email, "Your Bank Directory API key", _email_text(token))
        except (BotoCoreError, ClientError) as exc:
            # The link never went out, so it must not use up one of the address's links for the day.
            store.discard_signup_token(token)
            # Log the failure kind only: SES messages can contain addresses.
            code = exc.response.get("Error", {}).get("Code") if isinstance(exc, ClientError) else type(exc).__name__
            logger.error("Sign-up email could not be sent: %s", code)
            return (
                jsonify({"success": False, "message": "The sign-up email could not be sent. Try again later."}),
                503,
                _NO_STORE,
            )

    minutes = int(TOKEN_LIFETIME.total_seconds() // 60)
    return (
        jsonify(
            {
                "success": True,
                "message": f"If the address can receive email, a link to get your API key is on its way. "
                f"It works once, within {minutes} minutes.",
            }
        ),
        202,
        _NO_STORE,
    )


@signup_bp.route("/keys/verify", methods=["GET"])
def confirm_page():
    """Show a button that reveals the key, without using up the token."""
    token = request.args.get("token", "")
    if not _store().signup_token_is_valid(token):
        return _page("This link has expired or was already used", _expired_text()), 400, _PAGE_HEADERS
    body = (
        "<p>Press the button to see your API key. It is shown once, so have somewhere ready to keep it.</p>"
        '<form method="post" action="/api/keys/verify">'
        f'<input type="hidden" name="token" value="{html.escape(token, quote=True)}">'
        '<button type="submit">Show my API key</button></form>'
    )
    return _page("Get your API key", body), 200, _PAGE_HEADERS


@signup_bp.route("/keys/verify", methods=["POST"])
def verify():
    """
    Get your API key with the token from the sign-up email
    ---
    tags: [API keys]
    consumes: [application/json]
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [token]
          properties:
            token:
              type: string
    responses:
      200:
        description: The new API key, shown once
        schema:
          $ref: '#/definitions/IssuedApiKey'
      400:
        description: The token is unknown, already used or expired
        schema:
          $ref: '#/definitions/Error'
    """
    browser = not request.is_json
    email = _store().redeem_signup_token(str(_field("token") or ""))
    if email is None:
        if browser:
            return _page("This link has expired or was already used", _expired_text()), 400, _PAGE_HEADERS
        return jsonify({"success": False, "message": "This token has expired or was already used."}), 400, _NO_STORE

    key, record = _store().issue(email)
    note = f"Send it in the {KEY_HEADER} header. Any earlier key for this email address no longer works."
    if browser:
        body = (
            "<p>Your API key:</p>"
            f"<p><code>{html.escape(key)}</code></p>"
            f"<p>Copy it now: it is not shown again. {html.escape(note)}</p>"
        )
        return _page("Your API key", body), 200, _PAGE_HEADERS
    return (
        jsonify(
            {
                "success": True,
                "api_key": key,
                "prefix": record.prefix,
                "message": f"Store this key now; it is not shown again. {note}",
            }
        ),
        200,
        _NO_STORE,
    )


def _field(name: str) -> object:
    if request.is_json:
        body = request.get_json(silent=True)
        return body.get(name) if isinstance(body, dict) else None
    return request.form.get(name)


def _store() -> KeyStore:
    return current_app.extensions["bank_key_store"]


def _sender() -> EmailSender:
    return current_app.extensions["bank_email_sender"]


def _base_url() -> str:
    return current_app.extensions["bank_settings"].public_base_url


def _email_text(token: str) -> str:
    minutes = int(TOKEN_LIFETIME.total_seconds() // 60)
    return (
        "Hello,\n\n"
        f"Someone asked for an API key for the Bank Directory API ({_base_url()}) with this email address.\n\n"
        f"To get the key, open this link within {minutes} minutes:\n"
        f"{_base_url()}/api/keys/verify?token={quote(token)}\n\n"
        "The link works once. Getting a new key replaces any key this address had before.\n\n"
        "If you did not ask for this, you can ignore this email.\n"
    )


def _expired_text() -> str:
    return f"<p>Ask for a new link by sending your email address to <code>POST {html.escape(_base_url())}/api/keys/signup</code>.</p>"


def _page(title: str, body: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)} - Bank Directory API</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:40rem;margin:3rem auto;padding:0 1rem;line-height:1.5}"
        "code{word-break:break-all;background:#f2f2f2;padding:.2rem .4rem;border-radius:4px}"
        "button{font-size:1rem;padding:.6rem 1.2rem;cursor:pointer}</style></head>"
        f"<body><h1>{html.escape(title)}</h1>{body}</body></html>"
    )
