"""HTTP routes for country and bank lookups.

Routes only parse requests and shape responses. Bank data is loaded and
validated once at startup by `src.core.dataset` and kept on the app as
`app.extensions["bank_datasets"]`.
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, current_app, jsonify, request

from src.core.dataset import STATUSES, CountryDataset, search_text
from src.countries.profile import CountryProfile
from src.countries.registry import get_country_profile

banks_bp = Blueprint("banks", __name__)

MAX_LIMIT = 1000


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


@banks_bp.route("/countries/<country_code>/banks", methods=["GET"])
def list_banks(country_code: str):
    """
    List a country's banks
    ---
    tags: [Banks]
    parameters:
      - name: country_code
        in: path
        type: string
        required: true
        description: ISO 3166-1 alpha-2 or alpha-3 code, for example NG or NGA
      - name: q
        in: query
        type: string
        required: false
        description: Match banks whose name or id contains this text, ignoring case and accents
      - name: type
        in: query
        type: string
        required: false
        description: Comma-separated bank type codes from GET /api/countries/{country_code}
      - name: status
        in: query
        type: string
        required: false
        enum: [active, delisted, all]
        default: active
        description: >-
          active (the default) for banks the regulator lists today, delisted for banks it no longer
          lists, or all for both
      - name: limit
        in: query
        type: integer
        required: false
        description: Return at most this many banks (1-1000). Omit to return every match.
      - name: offset
        in: query
        type: integer
        required: false
        description: Skip this many matching banks first
      - name: has
        in: query
        type: string
        required: false
        description: >-
          Comma-separated identifier schemes every returned bank must have, for example nibss_code
          to list only banks that can receive NIP transfers
      - name: nibss_code
        in: query
        type: string
        required: false
        description: >-
          Nigeria: return the bank with this 6-digit NIBSS code. Every identifier scheme listed by
          GET /api/countries/{country_code} can be used as a filter the same way.
    responses:
      200:
        description: Matching banks sorted by name
      400:
        description: An invalid type, status, limit or offset
      404:
        description: The country is not supported yet
    """
    dataset = _find_dataset(country_code)
    if dataset is None:
        return _unsupported_country(country_code)

    try:
        statuses = _parse_status(request.args.get("status"))
        types = _parse_types(request.args.get("type"), dataset.profile)
        required = _parse_schemes(request.args.get("has"), dataset.profile)
        limit = _parse_int("limit", request.args.get("limit"), minimum=1, maximum=MAX_LIMIT)
        offset = _parse_int("offset", request.args.get("offset"), minimum=0) or 0
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400

    banks = [bank for bank in dataset.banks if bank["status"] in statuses]
    if types:
        banks = [bank for bank in banks if bank["type"] in types]
    if required:
        banks = [bank for bank in banks if required <= bank["identifiers"].keys()]
    for scheme in dataset.profile.identifier_schemes:
        value = request.args.get(scheme)
        if value is not None:
            banks = [bank for bank in banks if bank["identifiers"].get(scheme) == value.strip()]
    query = search_text(request.args.get("q", ""))
    if query:
        banks = [bank for bank in banks if query in search_text(bank["name"]) or query in bank["id"]]

    page = banks[offset : offset + limit if limit is not None else None]
    return jsonify(
        {
            "success": True,
            "country": _country_reference(dataset.profile),
            "total": len(banks),
            "offset": offset,
            "limit": limit,
            "banks": page,
        }
    ), 200


@banks_bp.route("/countries/<country_code>/banks/<bank_id>", methods=["GET"])
def get_bank(country_code: str, bank_id: str):
    """
    Get one bank
    ---
    tags: [Banks]
    parameters:
      - name: country_code
        in: path
        type: string
        required: true
        description: ISO 3166-1 alpha-2 or alpha-3 code, for example NG or NGA
      - name: bank_id
        in: path
        type: string
        required: true
        description: The bank's id from the bank list, for example access-bank
    responses:
      200:
        description: The bank, whether active or delisted
      404:
        description: The country is not supported, or it has no bank with this id
    """
    dataset = _find_dataset(country_code)
    if dataset is None:
        return _unsupported_country(country_code)
    bank = dataset.banks_by_id.get(bank_id.lower())
    if bank is None:
        return jsonify({"success": False, "message": f"No bank with id {bank_id!r} in {dataset.profile.name}."}), 404
    return jsonify({"success": True, "country": _country_reference(dataset.profile), "bank": bank}), 200


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


def _parse_status(value: str | None) -> set[str]:
    status = (value or "active").strip().lower()
    if status == "all":
        return set(STATUSES)
    if status not in STATUSES:
        raise ValueError(f"Unknown status {status}. Use one of: {', '.join(STATUSES)}, all.")
    return {status}


def _parse_types(value: str | None, profile: CountryProfile) -> set[str]:
    if not value:
        return set()
    types = {part.strip().lower() for part in value.split(",") if part.strip()}
    unknown = types - set(profile.bank_type_codes())
    if unknown:
        raise ValueError(
            f"Unknown bank type {', '.join(sorted(unknown))} for {profile.name}. "
            f"Use one of: {', '.join(profile.bank_type_codes())}."
        )
    return types


def _parse_schemes(value: str | None, profile: CountryProfile) -> set[str]:
    if not value:
        return set()
    schemes = {part.strip() for part in value.split(",") if part.strip()}
    unknown = schemes - set(profile.identifier_schemes)
    if unknown:
        raise ValueError(
            f"Unknown identifier scheme {', '.join(sorted(unknown))} for {profile.name}. "
            f"Use one of: {', '.join(profile.identifier_schemes)}."
        )
    return schemes


def _parse_int(name: str, value: str | None, *, minimum: int, maximum: int | None = None) -> int | None:
    if value is None or value == "":
        return None
    if not value.isdigit():
        raise ValueError(f"{name} must be a whole number.")
    number = int(value)
    if number < minimum or (maximum is not None and number > maximum):
        bounds = f"between {minimum} and {maximum}" if maximum is not None else f"at least {minimum}"
        raise ValueError(f"{name} must be {bounds}.")
    return number


def _country_reference(profile: CountryProfile) -> dict[str, str]:
    return {"alpha2": profile.alpha2, "alpha3": profile.alpha3, "name": profile.name}


def _active_banks(dataset: CountryDataset) -> list[dict[str, Any]]:
    return [bank for bank in dataset.banks if bank["status"] == "active"]


def _country_summary(dataset: CountryDataset) -> dict[str, Any]:
    active = len(_active_banks(dataset))
    return {
        **_country_reference(dataset.profile),
        "currency": dataset.profile.currency,
        "bank_count": active,
        "delisted_bank_count": len(dataset.banks) - active,
        "retrieved_on": dataset.retrieved_on,
    }


def _country_detail(dataset: CountryDataset) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for bank in _active_banks(dataset):
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
