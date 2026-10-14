"""HTTP routes for country and bank lookups.

Routes only parse requests and shape responses. Bank data is loaded and
validated once at startup by `src.core.dataset` and kept on the app as
`app.extensions["bank_datasets"]`.
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, current_app, jsonify

from src.core.dataset import CountryDataset
from src.countries.profile import CountryProfile
from src.countries.registry import get_country_profile

banks_bp = Blueprint("banks", __name__)


@banks_bp.route("/countries", methods=["GET"])
def list_countries():
    """
    List supported countries
    ---
    tags: [Countries]
    responses:
      200:
        description: Every country with bank data, with its bank count and data date
    """
    datasets = sorted(_datasets().values(), key=lambda dataset: dataset.profile.name)
    return jsonify({"success": True, "countries": [_country_summary(dataset) for dataset in datasets]}), 200


@banks_bp.route("/countries/<country_code>", methods=["GET"])
def get_country(country_code: str):
    """
    Get one country
    ---
    tags: [Countries]
    parameters:
      - name: country_code
        in: path
        type: string
        required: true
        description: ISO 3166-1 alpha-2 or alpha-3 code, for example NG or NGA
    responses:
      200:
        description: The country's bank types, identifier schemes and data sources
      404:
        description: The country is not supported yet
    """
    dataset = _find_dataset(country_code)
    if dataset is None:
        return _unsupported_country(country_code)
    return jsonify({"success": True, "country": _country_detail(dataset)}), 200


def _datasets() -> dict[str, CountryDataset]:
    return current_app.extensions["bank_datasets"]


def _find_dataset(country_code: str) -> CountryDataset | None:
    profile = get_country_profile(country_code)
    return _datasets().get(profile.alpha3) if profile else None


def _unsupported_country(country_code: str):
    code = country_code.strip().upper()[:16]
    return jsonify(
        {
            "success": False,
            "message": f"Unsupported country code: {code}. GET /api/countries lists the supported countries.",
        }
    ), 404


def _country_reference(profile: CountryProfile) -> dict[str, str]:
    return {"alpha2": profile.alpha2, "alpha3": profile.alpha3, "name": profile.name}


def _country_summary(dataset: CountryDataset) -> dict[str, Any]:
    return {
        **_country_reference(dataset.profile),
        "currency": dataset.profile.currency,
        "bank_count": len(dataset.banks),
        "retrieved_on": dataset.retrieved_on,
    }


def _country_detail(dataset: CountryDataset) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for bank in dataset.banks:
        counts[bank["type"]] = counts.get(bank["type"], 0) + 1
    return {
        **_country_summary(dataset),
        "bank_types": [
            {"code": bank_type.code, "name": bank_type.name, "bank_count": counts.get(bank_type.code, 0)}
            for bank_type in dataset.profile.bank_types
        ],
        "identifier_schemes": [
            {"code": code, "description": description} for code, description in dataset.profile.identifier_schemes.items()
        ],
        "sources": list(dataset.sources),
    }
