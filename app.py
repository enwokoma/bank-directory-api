"""Flask application entrypoint.

This file creates the web server, loads every country's bank data, wires the
route blueprint into Flask, and enables Swagger UI. Bank data loading and
validation live in `src/core/dataset.py`; country details live under
`src/countries/`.
"""

from flasgger import Swagger
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from src import __version__
from src.api.routes import banks_bp
from src.core.dataset import load_datasets

# Bank data only changes when a new version is deployed, so clients and CDNs
# may cache responses for an hour and revalidate with the ETag after that.
CACHE_CONTROL = "public, max-age=3600"

app = Flask(__name__)
app.json.compact = False  # type: ignore[attr-defined]
app.json.sort_keys = False  # type: ignore[attr-defined]
app.extensions["bank_datasets"] = load_datasets()

swagger_config = {
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
Swagger(app, config=swagger_config)

app.register_blueprint(banks_bp, url_prefix="/api")


@app.after_request
def add_public_api_headers(response):
    """Let browsers call the read-only API from any site, and let clients cache it."""
    if request.path.startswith("/api/"):
        response.headers["Access-Control-Allow-Origin"] = "*"
        if request.method == "GET" and response.status_code == 200:
            response.headers["Cache-Control"] = CACHE_CONTROL
            response.add_etag()
            response.make_conditional(request)
    return response


@app.errorhandler(HTTPException)
def http_error(error: HTTPException):
    """Return JSON rather than Flask's HTML page for unknown routes and methods."""
    return jsonify({"success": False, "message": error.description}), error.code


@app.route("/")
def health_check():
    """Return a small JSON response that load balancers can use as a health check."""
    return {"status": "healthy", "message": "Bank Directory API is live"}, 200


if __name__ == "__main__":
    # Debug mode serves Werkzeug's interactive debugger, so keep it on localhost.
    app.run(debug=True, port=5006)
