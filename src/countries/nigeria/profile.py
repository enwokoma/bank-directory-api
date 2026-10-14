"""Nigeria's country profile.

Bank categories follow the licence types the Central Bank of Nigeria lists under
Supervision > Financial Institutions.
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
    ),
    identifier_schemes={
        "cbn_institution_id": "Record ID in the Central Bank of Nigeria's financial institutions register",
    },
    refresh_module="src.countries.nigeria.refresh",
)
