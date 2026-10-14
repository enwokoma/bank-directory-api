# Changelog

Each release adds countries or refreshes existing ones. Data refreshes that only change bank lists are listed with the date the data was retrieved.

## 0.1.0 - Unreleased

### Added

- Flask API with Swagger UI at `/api-docs`: list countries, get a country, list a country's banks with search, type filters and paging, and get one bank.
- Country codes accepted as ISO 3166-1 alpha-2 or alpha-3 in any case.
- Cache headers with ETag revalidation, and cross-origin access, on every `GET` under `/api/`.
- Committed, validated data files per country, and a `python -m src.refresh` command that rebuilds them from official sources while keeping bank ids stable.
- Weekly workflow that reports when a committed data file no longer matches its source.
- Nigeria: 863 banks from the Central Bank of Nigeria's register (commercial, merchant, non-interest, payment service, microfinance and primary mortgage banks), retrieved 2026-10-14.
