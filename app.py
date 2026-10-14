"""Flask application entrypoint.

`create_app()` builds the web server: it loads every country's bank data,
wires the route blueprint into Flask, and enables Swagger UI. Settings come
from environment variables (see `src/core/settings.py`); with none set, the
API serves its data openly. Bank data loading and validation live in
`src/core/dataset.py`; country details live under `src/countries/`.
"""

from flasgger import Swagger
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from src import __version__
from src.api.access import install_access_control
from src.api.keys import keys_bp
from src.api.routes import banks_bp
from src.api.signup import signup_bp
from src.core.dataset import load_datasets
from src.core.email import SesEmailSender
from src.core.settings import Settings

# Bank data only changes when a new version is deployed, so clients and CDNs
# may cache responses for an hour and revalidate with the ETag after that.
CACHE_CONTROL = "public, max-age=3600"

# Headers a cross-site browser request may send, and response headers it may read.
CORS_ALLOWED_HEADERS = "X-API-Key, Authorization, Content-Type"
CORS_EXPOSED_HEADERS = "X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset, Retry-After"

# Once a browser has reached the API over HTTPS, it keeps using HTTPS for a year.
STRICT_TRANSPORT_SECURITY = "max-age=31536000"

SWAGGER_CONFIG = {
    "headers": [],
    "specs": [
        {
            "endpoint": "apispec_1",
            "route": "/apispec_1.json",
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/api-docs",
}


def create_app(settings: Settings | None = None) -> Flask:
    """Build the app. Without settings, they are read from the environment."""
    settings = settings or Settings.from_env()
    app = Flask(__name__)
    app.json.compact = False  # type: ignore[attr-defined]
    app.json.sort_keys = False  # type: ignore[attr-defined]
    app.extensions["bank_datasets"] = load_datasets()
    app.extensions["bank_settings"] = settings

    app.config["SWAGGER"] = {
        "title": "Bank Directory API",
        "version": __version__,
        "termsOfService": "",
        "uiversion": 3,
        "description": (
            "Lists of licensed banks by country, compiled from each country's official register. "
            "Countries are added gradually; GET /api/countries lists the ones available."
        ),
    }
    Swagger(app, config=SWAGGER_CONFIG)

    install_access_control(app, settings, limited=[banks_bp, keys_bp], signup=[signup_bp])
    app.extensions["bank_email_sender"] = SesEmailSender(settings.signup_email_from) if settings.signup_email_from else None
    app.register_blueprint(banks_bp, url_prefix="/api")
    app.register_blueprint(keys_bp, url_prefix="/api")
    app.register_blueprint(signup_bp, url_prefix="/api")
    app.after_request(add_public_api_headers)
    app.after_request(add_security_headers)
    app.register_error_handler(HTTPException, http_error)
    app.add_url_rule("/", "health_check", health_check)
    return app


def add_public_api_headers(response):
    """Let browsers call the API from any site, and let clients cache its data."""
    if request.path.startswith("/api/"):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Expose-Headers"] = CORS_EXPOSED_HEADERS
        if request.method == "OPTIONS":
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = CORS_ALLOWED_HEADERS
            response.headers["Access-Control-Max-Age"] = "86400"
        if request.method == "GET" and response.status_code == 200 and "Cache-Control" not in response.headers:
            response.headers["Cache-Control"] = CACHE_CONTROL
            response.add_etag()
            response.make_conditional(request)
    return response


def add_security_headers(response):
    """Stop browsers guessing content types, and keep them on HTTPS once they have used it.

    The app sends these itself so they are there whichever proxy is in front.
    HSTS only counts over HTTPS, which behind a trusted proxy is X-Forwarded-Proto.
    """
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    if request.is_secure:
        response.headers.setdefault("Strict-Transport-Security", STRICT_TRANSPORT_SECURITY)
    return response


def http_error(error: HTTPException):
    """Return JSON rather than Flask's HTML page for unknown routes and methods."""
    return jsonify({"success": False, "message": error.description}), error.code


def health_check():
    """Return a small JSON response that load balancers can use as a health check."""
    return {"status": "healthy", "message": "Bank Directory API is live"}, 200


app = create_app()


if __name__ == "__main__":
    # Debug mode serves Werkzeug's interactive debugger, so keep it on localhost.
    app.run(debug=True, port=5006)
