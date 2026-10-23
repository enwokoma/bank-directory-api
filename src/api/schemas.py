"""Swagger 2.0 definitions of every response the API sends, with examples.

Each route's documented responses reference one of these by name, as
`#/definitions/<Name>`, so the spec at /apispec_1.json is enough to generate
a typed client, and Swagger UI shows a real answer for each route. The
examples are the README's: Access Bank, Zenith Bank and the detection of
account number 0016563228. `tests/test_spec.py` checks that every definition
is referenced, that each example matches its definition, and that real
answers from every route match the definition their response declares.

Swagger 2.0 has no null type, so a field that can be null carries
`x-nullable: true`, the extension client generators understand.
"""

from __future__ import annotations

from typing import Any

JsonSchema = dict[str, Any]


def ref(name: str) -> JsonSchema:
    """A reference to one of the definitions, for a response's `schema`."""
    return {"$ref": f"#/definitions/{name}"}


def _object(description: str, properties: dict[str, JsonSchema], example: dict[str, Any]) -> JsonSchema:
    """An object whose every property is always present."""
    return {
        "type": "object",
        "description": description,
        "properties": properties,
        "required": list(properties),
        "example": example,
    }


def _field(kind: str, description: str, **extra: Any) -> JsonSchema:
    return {"type": kind, "description": description, **extra}


def _array(item: JsonSchema, description: str) -> JsonSchema:
    return {"type": "array", "description": description, "items": item}


def _success() -> JsonSchema:
    return _field("boolean", "true: the request succeeded", example=True)


# Examples, as the README shows them.

NIGERIA_REFERENCE: dict[str, Any] = {"alpha2": "NG", "alpha3": "NGA", "name": "Nigeria"}

NIGERIA_SUMMARY: dict[str, Any] = {
    **NIGERIA_REFERENCE,
    "currency": "NGN",
    "bank_count": 880,
    "delisted_bank_count": 0,
    "retrieved_on": "2026-10-21",
}

NIGERIA_DETAIL: dict[str, Any] = {
    **NIGERIA_SUMMARY,
    "bank_types": [
        {"code": "commercial", "name": "Commercial bank", "bank_count": 28},
        {"code": "merchant", "name": "Merchant bank", "bank_count": 5},
        {"code": "non_interest", "name": "Non-interest bank", "bank_count": 6},
        {"code": "payment_service", "name": "Payment service bank", "bank_count": 5},
        {"code": "microfinance", "name": "Microfinance bank", "bank_count": 786},
        {"code": "mortgage", "name": "Primary mortgage bank", "bank_count": 33},
        {"code": "mobile_money", "name": "Mobile money operator", "bank_count": 17},
    ],
    "identifier_schemes": [
        {
            "code": "cbn_institution_id",
            "description": "Record ID in the Central Bank of Nigeria's financial institutions register",
        },
        {
            "code": "nibss_code",
            "description": "6-digit NIBSS Instant Payment (NIP) institution code, used to send bank transfers",
        },
        {
            "code": "cbn_bank_code",
            "description": (
                "CBN bank code, from which NUBAN account numbers' check digits are computed and which payment "
                "providers use as the bank code: 3 digits for banks (058 for GTBank), 5 for other financial "
                "institutions (50515 for Moniepoint)"
            ),
        },
    ],
    "sources": [
        {
            "name": "Central Bank of Nigeria: Financial Institutions",
            "url": "https://www.cbn.gov.ng/supervision/finstitutions.html",
        },
        {
            "name": "Central Bank of Nigeria: Payment Service Providers",
            "url": "https://www.cbn.gov.ng/PaymentsSystem/PSPs.html",
        },
        {
            "name": "Central Bank of Nigeria: microfinance bank codes",
            "url": "https://www.cbn.gov.ng/Out/2014/OFISD/MFB%20Codes.pdf",
        },
        {"name": "Paystack: bank list (CBN bank codes)", "url": "https://paystack.com/docs/api/miscellaneous/#bank"},
        {"name": "NIBSS Instant Payment (NIP) institution list", "url": "https://nibss-plc.com.ng/nibss-instant-payment/"},
    ],
    "bank_detection": True,
}

ACCESS_BANK: dict[str, Any] = {
    "id": "access-bank",
    "name": "Access Bank Plc",
    "trading_name": "Access Bank Plc",
    "type": "commercial",
    "status": "active",
    "identifiers": {"cbn_institution_id": "1", "nibss_code": "000014", "cbn_bank_code": "044"},
}

ZENITH_BANK: dict[str, Any] = {
    "id": "zenith-bank",
    "name": "Zenith Bank Plc",
    "trading_name": "Zenith Bank Plc",
    "type": "commercial",
    "status": "active",
    "identifiers": {"cbn_institution_id": "24", "nibss_code": "000015", "cbn_bank_code": "057"},
}

# POST /api/detect-bank with {"account_number": "0016563228", "limit": 3}.
DETECTION_CANDIDATES: list[dict[str, Any]] = [
    {
        "confidence": 0.6678,
        "reasons": ["check_digit", "account_prefix"],
        "institution_code": "000058",
        "check_digit_valid": True,
        "bank": {
            "id": "guaranty-trust-bank",
            "name": "Guaranty Trust Bank Plc",
            "trading_name": "Guaranty Trust Bank Plc",
            "type": "commercial",
            "status": "active",
            "identifiers": {"cbn_institution_id": "8", "nibss_code": "000013", "cbn_bank_code": "058"},
        },
    },
    {
        "confidence": 0.2385,
        "reasons": ["check_digit"],
        "institution_code": "950515",
        "check_digit_valid": True,
        "bank": {
            "id": "moniepoint-mfb",
            "name": "Moniepoint MFB",
            "trading_name": "Moniepoint MFB",
            "type": "microfinance",
            "status": "active",
            "identifiers": {"cbn_institution_id": "3916", "nibss_code": "090405", "cbn_bank_code": "50515"},
        },
    },
    {
        "confidence": 0.0358,
        "reasons": ["check_digit"],
        "institution_code": "000070",
        "check_digit_valid": True,
        "bank": {
            "id": "fidelity-bank",
            "name": "Fidelity Bank Plc",
            "trading_name": "Fidelity Bank Plc",
            "type": "commercial",
            "status": "active",
            "identifiers": {"cbn_institution_id": "4", "nibss_code": "000007", "cbn_bank_code": "070"},
        },
    },
]

DETECTION: dict[str, Any] = {
    "success": True,
    "country": NIGERIA_REFERENCE,
    "account_number": "0016563228",
    "looks_like_phone_number": False,
    "best_guess": DETECTION_CANDIDATES[0],
    "recommended": {"coverage": 0.9, "confidence": 0.9063, "candidates": DETECTION_CANDIDATES[:2]},
    "candidates": DETECTION_CANDIDATES,
    "total_candidates": 44,
    "limit": 3,
}

ERROR: dict[str, Any] = {
    "success": False,
    "message": "Unknown identifier scheme swift for Nigeria. Use one of: cbn_institution_id, nibss_code, cbn_bank_code.",
}

API_KEY: dict[str, Any] = {
    "prefix": "bdk_3fQ9xL2m",
    "email": "you@example.com",
    "created_at": "2026-10-21T09:15:00+00:00",
    "last_used_at": "2026-10-22T14:00:00+00:00",
}

ISSUED_API_KEY: dict[str, Any] = {
    "success": True,
    "api_key": "bdk_3fQ9xL2mGk8vR1tYw7ZpB4nH6sJ0cD5eA9uF2iK3oLq",
    "prefix": "bdk_3fQ9xL2m",
    "message": (
        "Store this key now; it is not shown again. Send it in the X-API-Key header. "
        "Any earlier key for this email address no longer works."
    ),
}

SIGNUP_RECEIPT: dict[str, Any] = {
    "success": True,
    "message": "If the address can receive email, a link to get your API key is on its way. It works once, within 30 minutes.",
}


# Field descriptions, from the README's field tables.

COUNTRY_REFERENCE_FIELDS: dict[str, JsonSchema] = {
    "alpha2": _field("string", "ISO 3166-1 alpha-2 code", example="NG"),
    "alpha3": _field("string", "ISO 3166-1 alpha-3 code", example="NGA"),
    "name": _field("string", "The country's name", example="Nigeria"),
}

COUNTRY_SUMMARY_FIELDS: dict[str, JsonSchema] = {
    **COUNTRY_REFERENCE_FIELDS,
    "currency": _field("string", "ISO 4217 code of the country's currency", example="NGN"),
    "bank_count": _field("integer", "Active banks: the ones the regulator lists today", example=880),
    "delisted_bank_count": _field(
        "integer",
        "Banks the regulator no longer lists, kept in the data so stored ids and codes keep resolving",
        example=0,
    ),
    "retrieved_on": _field("string", "The date the data was retrieved from its sources", format="date", example="2026-10-21"),
}

BANK_FIELDS: dict[str, JsonSchema] = {
    "id": _field(
        "string",
        "Slug made from the bank's name when it was first listed, for example access-bank. It stays the same when "
        "the bank is renamed, so it is safe to store.",
        example="access-bank",
    ),
    "name": _field(
        "string",
        "The name exactly as the official register publishes it, including its capitalization. Only stray spaces "
        "and line breaks are removed.",
        example="Access Bank Plc",
    ),
    "trading_name": _field(
        "string",
        "The name the bank trades under today. It is the same as name unless the register still lists an older "
        "one, for example Nombank for the register's Amucha Microfinance Bank Limited. It is always set, so show "
        "it where people pick a bank, such as a transfer dropdown.",
        example="Access Bank Plc",
    ),
    "type": _field(
        "string",
        "One of the country's bank type codes, listed by GET /api/countries/{country_code}.",
        example="commercial",
    ),
    "status": _field(
        "string",
        "active while the regulator lists the bank, delisted once it no longer does: its licence was revoked, it "
        "merged into another bank, or it otherwise left the register.",
        enum=["active", "delisted"],
        example="active",
    ),
    "identifiers": {
        "type": "object",
        "description": (
            "Codes for the bank under the schemes the country declares, listed by GET /api/countries/{country_code}. "
            "A scheme is left out when the bank has no code under it."
        ),
        "additionalProperties": {"type": "string"},
        "example": ACCESS_BANK["identifiers"],
    },
}

CANDIDATE_FIELDS: dict[str, JsonSchema] = {
    "confidence": _field(
        "number",
        "The estimated probability that this is the right institution. The confidences of all candidates, not only "
        "the returned ones, add up to 1; a candidate whose confidence rounds to 0 is left out.",
        minimum=0,
        maximum=1,
        example=0.6678,
    ),
    "reasons": _array(
        {"type": "string"},
        "The evidence for it, strongest first: hint (the hint names it), phone_number_account (the number looks "
        "like a mobile number and the institution issues those), check_digit (the check digit is the one its code "
        "gives), account_prefix (the number starts with digits it is known to use). An empty list means nothing "
        "counts for it, but nothing rules it out either: it issues account numbers outside NUBAN.",
    ),
    "institution_code": _field(
        "string",
        "The 6-digit code the check digit was tested with: 000 and the 3-digit CBN bank code for banks, 9 and the "
        "5-digit code for other financial institutions, or the NIBSS code for institutions whose CBN bank code is "
        "not known.",
        example="000058",
    ),
    "check_digit_valid": _field("boolean", "Whether the number's check digit is the one that code gives.", example=True),
    "bank": ref("Bank"),
}

RECOMMENDED_FIELDS: dict[str, JsonSchema] = {
    "coverage": _field(
        "number",
        "The coverage asked for: how sure the block should be of holding the right institution, 0.5 to 0.99 (default 0.9).",
        example=0.9,
    ),
    "confidence": _field(
        "number",
        "The probability that the right institution is among the recommended candidates: their confidences added up.",
        example=0.9063,
    ),
    "candidates": _array(
        ref("DetectionCandidate"),
        "The candidates to try first, most likely first: taken from the top until their confidences add up to "
        "coverage, and never more than five.",
    ),
}


DEFINITIONS: dict[str, JsonSchema] = {
    "Error": _object(
        "A failed request: 400 for a bad parameter, 404 for an unknown country, bank or route, and in hosted "
        "mode 401 for a bad API key, 429 for too many requests and 503 when a sign-up email could not be sent.",
        {
            "success": _field("boolean", "false: the request failed", example=False),
            "message": _field("string", "What went wrong, and where it helps, what to send instead", example=ERROR["message"]),
        },
        ERROR,
    ),
    "CountryReference": _object(
        "The country a response is about.",
        COUNTRY_REFERENCE_FIELDS,
        NIGERIA_REFERENCE,
    ),
    "CountrySummary": _object(
        "A country with bank data, as GET /api/countries lists it.",
        COUNTRY_SUMMARY_FIELDS,
        NIGERIA_SUMMARY,
    ),
    "BankType": _object(
        "One category of licensed institution, with its count of active banks.",
        {
            "code": _field("string", "The code to send as the bank list's type filter", example="commercial"),
            "name": _field("string", "The category's name", example="Commercial bank"),
            "bank_count": _field("integer", "Active banks of this type", example=28),
        },
        NIGERIA_DETAIL["bank_types"][0],
    ),
    "IdentifierScheme": _object(
        "One kind of code the country's banks carry.",
        {
            "code": _field(
                "string",
                "The key of the scheme in each bank's identifiers, and the query parameter that finds a bank by its code",
                example="nibss_code",
            ),
            "description": _field(
                "string", "What the code is and who issues it", example=NIGERIA_DETAIL["identifier_schemes"][1]["description"]
            ),
        },
        NIGERIA_DETAIL["identifier_schemes"][1],
    ),
    "Source": _object(
        "An official list the country's data was compiled from.",
        {
            "name": _field("string", "The publisher and the list", example=NIGERIA_DETAIL["sources"][0]["name"]),
            "url": _field("string", "Where the list is published", format="uri", example=NIGERIA_DETAIL["sources"][0]["url"]),
        },
        NIGERIA_DETAIL["sources"][0],
    ),
    "CountryDetail": _object(
        "A country with its bank types, identifier schemes and data sources, as GET /api/countries/{country_code} "
        "returns it. bank_count and the counts per type cover active banks.",
        {
            **COUNTRY_SUMMARY_FIELDS,
            "bank_types": _array(
                ref("BankType"), "The country's bank types in display order, each with its count of active banks"
            ),
            "identifier_schemes": _array(ref("IdentifierScheme"), "The identifier schemes its banks carry"),
            "sources": _array(ref("Source"), "The official lists the data was compiled from"),
            "bank_detection": _field(
                "boolean",
                "Whether the country's account numbers say which bank issued them, so the detect-bank routes work for it",
                example=True,
            ),
        },
        NIGERIA_DETAIL,
    ),
    "CountryList": _object(
        "Every country with bank data, sorted by name.",
        {"success": _success(), "countries": _array(ref("CountrySummary"), "The countries, sorted by name")},
        {"success": True, "countries": [NIGERIA_SUMMARY]},
    ),
    "CountryLookup": _object(
        "One country, in full.",
        {"success": _success(), "country": ref("CountryDetail")},
        {"success": True, "country": NIGERIA_DETAIL},
    ),
    "Bank": _object(
        "A licensed institution, with its codes under the country's identifier schemes.",
        BANK_FIELDS,
        ACCESS_BANK,
    ),
    "BankList": _object(
        "A page of a country's banks, sorted by name.",
        {
            "success": _success(),
            "country": ref("CountryReference"),
            "total": _field("integer", "How many banks match, before paging", example=1),
            "offset": _field("integer", "How many matching banks were skipped", example=0),
            "limit": _field(
                "integer",
                "The page size asked for, or null when every match is returned",
                example=None,
                **{"x-nullable": True},
            ),
            "banks": _array(ref("Bank"), "The requested page of matching banks, sorted by name"),
        },
        {"success": True, "country": NIGERIA_REFERENCE, "total": 1, "offset": 0, "limit": None, "banks": [ZENITH_BANK]},
    ),
    "BankLookup": _object(
        "One bank, whether active or delisted.",
        {"success": _success(), "country": ref("CountryReference"), "bank": ref("Bank")},
        {"success": True, "country": NIGERIA_REFERENCE, "bank": ACCESS_BANK},
    ),
    "DetectionCandidate": _object(
        "One institution the account number can belong to, with the evidence for it.",
        CANDIDATE_FIELDS,
        DETECTION_CANDIDATES[0],
    ),
    "Recommended": _object(
        "The candidates to try first, and how likely the right institution is to be among them.",
        RECOMMENDED_FIELDS,
        DETECTION["recommended"],
    ),
    "Detection": _object(
        "Which institutions an account number can belong to, most likely first.",
        {
            "success": _success(),
            "country": ref("CountryReference"),
            "account_number": _field(
                "string",
                "The account number the candidates were found for: the digits sent, with spaces and dashes removed "
                "and a mobile number reduced to the wallet account number it stands for",
                example="0016563228",
            ),
            "looks_like_phone_number": _field(
                "boolean",
                "Whether the number looks like a mobile number, which counts for the institutions that give "
                "customers their phone number as account number",
                example=False,
            ),
            "best_guess": {
                "description": "The first candidate, repeated, or null when no institution can have issued the number",
                "allOf": [ref("DetectionCandidate")],
                "x-nullable": True,
            },
            "recommended": ref("Recommended"),
            "candidates": _array(
                ref("DetectionCandidate"),
                "Every institution the number can belong to, most likely first, at most limit of them",
            ),
            "total_candidates": _field("integer", "How many candidates there are in all, whatever the limit", example=44),
            "limit": _field("integer", "The most candidates returned: the limit asked for, or 10", example=3),
        },
        DETECTION,
    ),
    "ApiKey": _object(
        "An API key as the server knows it. The key itself is never stored, only its hash.",
        {
            "prefix": _field(
                "string", "The key's first 12 characters, which is how it is referred to", example=API_KEY["prefix"]
            ),
            "email": _field("string", "The address the key was issued to", example=API_KEY["email"]),
            "created_at": _field("string", "When the key was issued", format="date-time", example=API_KEY["created_at"]),
            "last_used_at": _field(
                "string",
                "When the key was last used, kept to the hour, or null if it has not been used yet",
                format="date-time",
                example=API_KEY["last_used_at"],
                **{"x-nullable": True},
            ),
        },
        API_KEY,
    ),
    "ApiKeyLookup": _object(
        "The API key the request was sent with.",
        {
            "success": _success(),
            "key": ref("ApiKey"),
            "rate_limit": _field(
                "string",
                "The key's rate limits, separated by semicolons",
                example="120 per minute;20000 per day",
            ),
        },
        {"success": True, "key": API_KEY, "rate_limit": "120 per minute;20000 per day"},
    ),
    "SignupReceipt": _object(
        "The answer to a sign-up, the same whether or not the address already has a key.",
        {"success": _success(), "message": _field("string", "What happens next", example=SIGNUP_RECEIPT["message"])},
        SIGNUP_RECEIPT,
    ),
    "IssuedApiKey": _object(
        "A new API key, shown once.",
        {
            "success": _success(),
            "api_key": _field(
                "string",
                "The key: bdk_ followed by 43 URL-safe characters. Store it now; it is not shown again.",
                example=ISSUED_API_KEY["api_key"],
            ),
            "prefix": _field(
                "string", "The key's first 12 characters, which is how it is referred to", example=ISSUED_API_KEY["prefix"]
            ),
            "message": _field("string", "How to use the key", example=ISSUED_API_KEY["message"]),
        },
        ISSUED_API_KEY,
    ),
}
