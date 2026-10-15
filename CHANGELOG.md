# Changelog

Each release adds countries or refreshes existing ones. Data refreshes that only change bank lists are listed with the date the data was retrieved.

## 0.3.4 - 2026-10-15

### Fixed

- A sign-up email that could not be sent no longer uses up one of the address's three links for the day.

## 0.3.3 - 2026-10-15

### Fixed

- Sign-up emails failed with "The sign-up email could not be sent". boto3 reads the region only from `AWS_DEFAULT_REGION`, so the `AWS_REGION` that every deployment sets never reached the SES client. The API now reads `AWS_REGION` itself and passes it on.
- gunicorn no longer tries to create its control socket, which failed on the container's read-only filesystem and logged an error at every start.

## 0.3.2 - 2026-10-15

### Fixed

- The API now sends `X-Content-Type-Options: nosniff` on every response and, over HTTPS, `Strict-Transport-Security` itself, so both are present behind any proxy, including Coolify's, not only behind the bundled Caddy configuration.

## 0.3.1 - 2026-10-14

### Added

- Each release tag publishes the image to `ghcr.io/enwokoma/bank-directory-api` for amd64 and arm64, built natively per architecture.
- `deploy/coolify/docker-compose.yml`, for running the API as a Coolify service with the published image, and a Coolify section in the deployment guide.

### Fixed

- The container's health check now allows 60 seconds for the workers to start, so a slow first boot is no longer reported as unhealthy.

## 0.3.0 - 2026-10-14

### Added

- Release downloads: every country's data file is attached to each GitHub release with a `SHA256SUMS` file, starting with v0.2.0, and `scripts/upload-release-assets.sh` attaches them.
- A "Use it in your project" section in the README, with download links and code to fetch the data.
- Hosted mode, off unless configured: rate limits per client IP and per API key, shared through Redis, with `X-RateLimit-*` headers and JSON 429s.
- API keys stored only as hashes, sent in `X-API-Key` or as a Bearer token, with self-service sign-up proved by email through Amazon SES, `GET /api/keys/me`, and `python -m src.keys_admin` to list, issue and revoke keys.
- A Docker image, a Docker Compose deployment with Redis, a Caddy block for banks.example.com, and a deployment guide for AWS.
- `deploy/aws/provision.sh`, which sets up a dedicated EC2 instance from AWS CloudShell, and `deploy/docker-compose.standalone.yml`, which runs Caddy alongside the API on a server without one.

### Changed

- The app is built by `create_app()`, with settings read from environment variables.

## 0.2.0 - 2026-10-14

### Added

- Nigeria: 6-digit NIBSS Instant Payment (NIP) codes, the codes used to send bank transfers, as the `nibss_code` identifier.
- Nigeria: the 17 licensed mobile money operators, such as OPay, PalmPay and Paga, as the `mobile_money` bank type.
- `has` filter, such as `?has=nibss_code`, to list only banks that have an identifier, and filters by any identifier, such as `?nibss_code=000014`.
- Refresh settings for sources that need a key, read from a local `.env` file or CI secrets.
- Up to five relayed copies of the NIP institution list can be combined, since a single copy can leave institutions out.
- `python -m src.refresh NGA --verbose` lists every code match with its name in the NIP list, for review.

### Changed

- Bank ids now carry over between refreshes through any shared identifier, or the exact name, not only the first identifier scheme.
- Identifier values are checked against a pattern per scheme, and no value may belong to two banks.

## 0.1.0 - 2026-10-14

Not tagged on its own; first released as part of 0.2.0.

### Added

- Flask API with Swagger UI at `/api-docs`: list countries, get a country, list a country's banks with search, type filters and paging, and get one bank.
- Country codes accepted as ISO 3166-1 alpha-2 or alpha-3 in any case.
- Cache headers with ETag revalidation, and cross-origin access, on every `GET` under `/api/`.
- Committed, validated data files per country, and a `python -m src.refresh` command that rebuilds them from official sources while keeping bank ids stable.
- Weekly workflow that reports when a committed data file no longer matches its source.
- Nigeria: 863 banks from the Central Bank of Nigeria's register (commercial, merchant, non-interest, payment service, microfinance and primary mortgage banks), retrieved 2026-10-14.
