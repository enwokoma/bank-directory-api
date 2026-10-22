"""HTTP routes for country and bank lookups, and for detecting a bank from an account number.

Routes only parse requests and shape responses. Bank data is loaded and
validated once at startup by `src.core.dataset` and kept on the app as
`app.extensions["bank_datasets"]`. Detection is done by the country's
detection module (see `src.core.detection`).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from flasgger import swag_from
from flask import Blueprint, current_app, jsonify, request

from src.core.dataset import STATUSES, CountryDataset, search_text
from src.core.detection import DEFAULT_COVERAGE, MAX_RECOMMENDED, Candidate, get_detector, recommended_count
from src.countries.profile import CountryProfile
from src.countries.registry import get_country_profile

banks_bp = Blueprint("banks", __name__)

MAX_LIMIT = 1000
DETECTION_DEFAULT_LIMIT = 10
DETECTION_MAX_LIMIT = 100
MAX_HINT_LENGTH = 200
MIN_COVERAGE = 0.5
MAX_COVERAGE = 0.99


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
        description: Match banks whose name, trading name or id contains this text, ignoring case and accents
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
          GET /api/countries/{country_code} can be used as a filter the same way, such as
          cbn_bank_code=058.
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
        return _bad_request(str(exc))

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
        banks = [
            bank
            for bank in banks
            if query in search_text(bank["name"]) or query in search_text(bank["trading_name"]) or query in bank["id"]
        ]

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


_DETECTION_DESCRIPTION = (
    "Which institution an account number belongs to, from the number alone. A Nigerian account number ends in "
    "a check digit computed from the issuing institution's CBN bank code, so the number is tested against every "
    "institution that can receive transfers: those whose code gives a different digit are ruled out, and the rest "
    "are ranked by how common they are, by whether the number looks like a mobile number (OPay, PalmPay, "
    "Moniepoint and the payment service banks give customers their phone number as account number), by leading "
    "digits banks are known to use, and by the hint. The check digit carries one digit of information, so several "
    "institutions usually remain: try them in order with your payment provider's name enquiry, and send the text "
    "the number was copied with as the hint. Each candidate's confidence is the estimated probability that it is "
    "the right institution; the confidences of all candidates add up to 1."
)


def _detection_spec(*, country_in_path: bool, post: bool) -> dict[str, Any]:
    """Build the Swagger spec of one detect-bank route, so the four share one description."""
    fields: dict[str, dict[str, Any]] = {
        "account_number": {
            "type": "string",
            "description": (
                "The 10-digit account number. Spaces and dashes are ignored, and a Nigerian mobile number written "
                "in full, such as 08012345678 or +2348012345678, is read as the wallet account number it stands for."
            ),
        },
        "hint": {
            "type": "string",
            "description": (
                "Text copied along with the number, such as 'GTBank 0123456789 John Doe'. An institution it names "
                f"outranks every other candidate. At most {MAX_HINT_LENGTH} characters."
            ),
        },
        "type": {
            "type": "string",
            "description": "Comma-separated bank type codes to consider, for example commercial,mobile_money. "
            "Default: every type.",
        },
        "limit": {
            "type": "integer",
            "description": (
                f"Return at most this many candidates, 1 to {DETECTION_MAX_LIMIT} (default "
                f"{DETECTION_DEFAULT_LIMIT}). total_candidates counts every one regardless."
            ),
        },
        "coverage": {
            "type": "number",
            "description": (
                f"How sure the recommended block should be of holding the right institution, {MIN_COVERAGE} to "
                f"{MAX_COVERAGE} (default {DEFAULT_COVERAGE}): candidates are recommended from the top until their "
                f"confidences add up to this, at most {MAX_RECOMMENDED} of them."
            ),
        },
    }
    if not country_in_path:
        fields["country"] = {
            "type": "string",
            "description": "ISO 3166-1 alpha-2 or alpha-3 code, such as NG. Optional while Nigeria is the only "
            "country with bank detection.",
        }
    parameters: list[dict[str, Any]] = []
    if country_in_path:
        parameters.append(
            {
                "name": "country_code",
                "in": "path",
                "type": "string",
                "required": True,
                "description": "ISO 3166-1 alpha-2 or alpha-3 code, for example NG or NGA",
            }
        )
    if post:
        parameters.append(
            {
                "name": "body",
                "in": "body",
                "required": True,
                "schema": {
                    "type": "object",
                    "required": ["account_number"],
                    "properties": fields,
                    "example": {"account_number": "0123456789", "hint": "GTBank 0123456789 John Doe"},
                },
            }
        )
    else:
        parameters += [
            {"name": name, "in": "query", "required": name == "account_number", **field} for name, field in fields.items()
        ]
    spec: dict[str, Any] = {
        "tags": ["Detection"],
        "summary": "Detect the bank an account number belongs to",
        "description": _DETECTION_DESCRIPTION,
        "parameters": parameters,
        "responses": {
            "200": {
                "description": "The candidates, most likely first, each with its confidence and the evidence for it, "
                "and the recommended ones to try first"
            },
            "400": {"description": "A missing or malformed account number, or an invalid hint, type, limit or coverage"},
            "404": {"description": "The country is not supported, or has no bank detection"},
        },
    }
    if post:
        spec["consumes"] = ["application/json"]
    return spec


@banks_bp.route("/detect-bank", methods=["GET"])
@swag_from(_detection_spec(country_in_path=False, post=False))
def detect_bank():
    return _detect_bank(None, request.args)


@banks_bp.route("/detect-bank", methods=["POST"])
@swag_from(_detection_spec(country_in_path=False, post=True))
def detect_bank_from_body():
    return _detect_bank(None, _request_body())


@banks_bp.route("/countries/<country_code>/detect-bank", methods=["GET"])
@swag_from(_detection_spec(country_in_path=True, post=False))
def detect_bank_in_country(country_code: str):
    return _detect_bank(country_code, request.args)


@banks_bp.route("/countries/<country_code>/detect-bank", methods=["POST"])
@swag_from(_detection_spec(country_in_path=True, post=True))
def detect_bank_in_country_from_body(country_code: str):
    return _detect_bank(country_code, _request_body())


def _detect_bank(country_code: str | None, params: Mapping[str, Any] | None):
    if params is None:
        return _bad_request('The request body must be a JSON object such as {"account_number": "0123456789"}.')
    try:
        dataset, failure = _detection_dataset(country_code or _text_param(params, "country"))
        if dataset is None:
            return failure
        account_number = _text_param(params, "account_number")
        if not account_number:
            raise ValueError("account_number is required.")
        hint = _text_param(params, "hint")
        if hint and len(hint) > MAX_HINT_LENGTH:
            raise ValueError(f"hint must be at most {MAX_HINT_LENGTH} characters.")
        types = _parse_types(_text_param(params, "type"), dataset.profile)
        limit = _parse_int("limit", _text_param(params, "limit"), minimum=1, maximum=DETECTION_MAX_LIMIT)
        coverage = _parse_fraction("coverage", _text_param(params, "coverage"), minimum=MIN_COVERAGE, maximum=MAX_COVERAGE)
        detector = get_detector(dataset.profile)
        if detector is None:  # Guarded by _detection_dataset; kept for the type checker.
            return failure
        detection = detector(dataset, account_number, hint=hint, types=types)
    except ValueError as exc:
        return _bad_request(str(exc))

    limit = limit or DETECTION_DEFAULT_LIMIT
    coverage = DEFAULT_COVERAGE if coverage is None else coverage
    candidates = [_candidate_json(candidate) for candidate in detection.candidates[:limit]]
    recommended = candidates[: recommended_count(detection.candidates, coverage, limit=min(MAX_RECOMMENDED, limit))]
    return jsonify(
        {
            "success": True,
            "country": _country_reference(dataset.profile),
            "account_number": detection.account_number,
            "looks_like_phone_number": detection.looks_like_phone_number,
            "best_guess": candidates[0] if candidates else None,
            "recommended": {
                "coverage": coverage,
                "confidence": round(sum(candidate["confidence"] for candidate in recommended), 4),
                "candidates": recommended,
            },
            "candidates": candidates,
            "total_candidates": len(detection.candidates),
            "limit": limit,
        }
    ), 200


def _candidate_json(candidate: Candidate) -> dict[str, Any]:
    return {
        "confidence": candidate.confidence,
        "reasons": list(candidate.reasons),
        "institution_code": candidate.institution_code,
        "check_digit_valid": candidate.check_digit_valid,
        "bank": candidate.bank,
    }


def _detection_dataset(country_code: str | None) -> tuple[CountryDataset | None, Any]:
    """Find the dataset to detect in, or the error response to send instead."""
    if country_code is None:
        supported = [dataset for dataset in _datasets().values() if dataset.profile.detection_module]
        if len(supported) == 1:
            return supported[0], None
        codes = ", ".join(sorted(dataset.profile.alpha2 for dataset in supported))
        return None, _bad_request(f"country is required. Countries with bank detection: {codes or 'none'}.")
    dataset = _find_dataset(country_code)
    if dataset is None:
        return None, _unsupported_country(country_code)
    if not dataset.profile.detection_module:
        message = f"Bank detection is not available for {dataset.profile.name} yet."
        return None, (jsonify({"success": False, "message": message}), 404)
    return dataset, None


def _request_body() -> Mapping[str, Any] | None:
    """The POST parameters: a JSON object, or the fields of a form-encoded request. None for anything else."""
    if request.is_json:
        body = request.get_json(silent=True)
        return body if isinstance(body, dict) else None
    return request.form


def _text_param(params: Mapping[str, Any], name: str) -> str | None:
    """Read one parameter as text, from the query string or a JSON body."""
    value = params.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f"{name} must be a string.")
    if not isinstance(value, str):
        if name == "account_number":
            raise ValueError("Send account_number as a string, so that its leading zeros are kept.")
        value = str(value)
    return value.strip() or None


def _datasets() -> dict[str, CountryDataset]:
    return current_app.extensions["bank_datasets"]


def _find_dataset(country_code: str) -> CountryDataset | None:
    profile = get_country_profile(country_code)
    return _datasets().get(profile.alpha3) if profile else None


def _bad_request(message: str):
    return jsonify({"success": False, "message": message}), 400


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


def _parse_fraction(name: str, value: str | None, *, minimum: float, maximum: float) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except ValueError:
        raise ValueError(f"{name} must be a number between {minimum} and {maximum}.") from None
    if not minimum <= number <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return number


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
        "bank_detection": bool(dataset.profile.detection_module),
    }
