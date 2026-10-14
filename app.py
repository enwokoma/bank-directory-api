"""Flask application entrypoint.

This file creates the web server, loads every country's bank data, wires the
route blueprint into Flask, and enables Swagger UI. Bank data loading and
validation live in `src/core/dataset.py`; country details live under
`src/countries/`.
"""

from flasgger import Swagger
from flask import Flask

from src.api.routes import banks_bp
from src.core.dataset import load_datasets

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
    "version": "0.1.0",
    "termsOfService": "",
    "uiversion": 3,
    "description": (
        "Lists of licensed banks by country, compiled from each country's official register. "
        "Countries are added gradually; GET /api/countries lists the ones available."
    ),
}
Swagger(app, config=swagger_config)

app.register_blueprint(banks_bp, url_prefix="/api")


@app.route("/")
def health_check():
    """Return a small JSON response that load balancers can use as a health check."""
    return {"status": "healthy", "message": "Bank Directory API is live"}, 200


if __name__ == "__main__":
    # Debug mode serves Werkzeug's interactive debugger, so keep it on localhost.
    app.run(debug=True, port=5006)
