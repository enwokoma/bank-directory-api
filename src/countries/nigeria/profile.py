"""Nigeria's country profile.

Bank categories follow the licence types the Central Bank of Nigeria lists under
Supervision > Financial Institutions, plus mobile money operators from its
Payments System pages, which receive bank transfers like banks do.
"""

from src.countries.profile import BankType, CountryProfile

NIGERIA_PROFILE = CountryProfile(
    alpha2="NG",
    alpha3="NGA",
    name="Nigeria",
    currency="NGN",
    bank_types=(
        BankType("commercial", "Commercial bank"),
        BankType("merchant", "Merchant bank"),
        BankType("non_interest", "Non-interest bank"),
        BankType("payment_service", "Payment service bank"),
        BankType("microfinance", "Microfinance bank"),
        BankType("mortgage", "Primary mortgage bank"),
        BankType("mobile_money", "Mobile money operator"),
    ),
    identifier_schemes={
        "cbn_institution_id": "Record ID in the Central Bank of Nigeria's financial institutions register",
        "nibss_code": "6-digit NIBSS Instant Payment (NIP) institution code, used to send bank transfers",
        "cbn_bank_code": (
            "CBN bank code, from which NUBAN account numbers' check digits are computed and which payment "
            "providers use as the bank code: 3 digits for banks (058 for GTBank), 5 for other financial "
            "institutions (50515 for Moniepoint)"
        ),
    },
    identifier_patterns={
        "cbn_institution_id": r"[0-9]+",
        "nibss_code": r"[0-9]{6}",
        "cbn_bank_code": r"[0-9]{3}|[0-9]{5}",
    },
    refresh_module="src.countries.nigeria.refresh",
    detection_module="src.countries.nigeria.detection",
)
