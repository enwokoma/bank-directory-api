# Changelog

Each release adds countries or refreshes existing ones. Data refreshes that only change bank lists are listed with the date the data was retrieved.

## 0.2.0 - Unreleased

### Added

- Nigeria: 6-digit NIBSS Instant Payment (NIP) codes, the codes used to send bank transfers, as the `nibss_code` identifier.
- Nigeria: the 17 licensed mobile money operators, such as OPay, PalmPay and Paga, as the `mobile_money` bank type.
- `has` filter, such as `?has=nibss_code`, to list only banks that have an identifier, and filters by any identifier, such as `?nibss_code=000014`.
- Refresh settings for sources that need a key, read from a local `.env` file or CI secrets.

### Changed

- Bank ids now carry over between refreshes through any shared identifier, or the exact name, not only the first identifier scheme.
- Identifier values are checked against a pattern per scheme, and no value may belong to two banks.

## 0.1.0 - Unreleased

### Added

- Flask API with Swagger UI at `/api-docs`: list countries, get a country, list a country's banks with search, type filters and paging, and get one bank.
- Country codes accepted as ISO 3166-1 alpha-2 or alpha-3 in any case.
- Cache headers with ETag revalidation, and cross-origin access, on every `GET` under `/api/`.
- Committed, validated data files per country, and a `python -m src.refresh` command that rebuilds them from official sources while keeping bank ids stable.
- Weekly workflow that reports when a committed data file no longer matches its source.
- Nigeria: 863 banks from the Central Bank of Nigeria's register (commercial, merchant, non-interest, payment service, microfinance and primary mortgage banks), retrieved 2026-10-14.
