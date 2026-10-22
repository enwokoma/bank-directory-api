# Changelog

Each release adds countries or refreshes existing ones. Data refreshes that only change bank lists are listed with the date the data was retrieved.

## Unreleased

### Added

- Bank detection answers carry a `recommended` block: the candidates to try first, taken from the top until their confidences add up to `coverage` (a new parameter, 0.5 to 0.99, default 0.9), at most five, with the probability that the right institution is among them.

- Nigeria: CBN bank codes for 422 more institutions, from the CBN's own list of microfinance bank codes matched to the register by name where the name is unique in both lists. 594 of the 880 institutions now have one, 307 of the 417 on NIP, and the data cites the CBN list as a source.
- `other_bank_codes` in `account_detection.json`: other codes an institution has issued account numbers under, which bank detection tests too. Accion, Bosak, Chikum and FUT Minna used 3-digit NIBSS codes before the CBN's 5-digit ones, which payment providers still list; their `cbn_bank_code` is now the CBN's.

### Changed

- Candidates whose confidence rounds to 0, as every other one does once a hint names an institution, are left out of bank detection answers.

## 0.5.0 - 2026-10-22

### Added

- Bank detection from an account number: `GET` or `POST /api/detect-bank`, and the same under `/api/countries/{country_code}/detect-bank`, takes a 10-digit Nigerian account number, or a mobile number for a wallet account, and returns the institutions it can belong to, most likely first, each with a `confidence` and the evidence for it. The check digit of a NUBAN account number is computed from the issuing institution's CBN bank code, so institutions whose code gives another digit are ruled out, and the rest are ranked by how common they are, by whether the number looks like a mobile number (OPay, PalmPay, Moniepoint, Paga and the payment service banks use phone numbers as account numbers), by leading digits banks are known to use, and by a `hint`, the text the number was copied with. `type` and `limit` narrow the answer.
- Nigeria: the `cbn_bank_code` identifier, the CBN's 3-digit bank code (`058` for GTBank) or 5-digit code for other financial institutions (`50515` for Moniepoint), for 172 institutions, from the reviewed file `src/countries/nigeria/cbn_bank_codes.json`. It is the code payment providers such as Paystack take as the bank code, and the one NUBAN check digits are computed from. The bank list can be filtered by it, `?cbn_bank_code=058`.
- `src/countries/nigeria/account_detection.json`: reviewed shares, phone-number account fractions, leading digits and aliases per institution, which rank the candidates and can be calibrated without code changes.
- `GET /api/countries/{country_code}` says whether the country has `bank_detection`, and Nigeria's sources cite Paystack's bank list for the CBN bank codes.
- Nigeria: 44 more institutions have NIBSS codes, 417 of 880 (up from 373): 42 matched from Paystack's bank list, read as a third relayed NIP list, plus reviewed matches for Summit Bank (`080003`) and Visual ICT (`100023`), which trades as TagPay.
- The refresh reads Paystack's `nip_sort_code` field as a NIBSS code, so Paystack's bank list, called with `currency=NGN&include_nip_sort_code=true`, can be set as a NIP list source. `.env.example` and the scheduled data check carry the `_3` settings for it.

### Changed

- Nigeria's data was retrieved on 2026-10-21. Its identifiers gain the `cbn_bank_code` scheme and its sources a fourth entry, Paystack's bank list; nothing is removed or renamed.

## 0.4.0 - 2026-10-20

### Added

- `compose.yaml` runs the API on your own machine with `docker compose up --build`, and the README explains running the published image with `docker run`.
- The README describes the public API at banks.globbapay.com, and links to the data file that always has the latest data, as well as to pinned releases.
- Every bank has a `status`, `active` or `delisted`. A bank the regulator stops listing now stays in its data file as `delisted` instead of being removed, so stored ids and codes keep resolving; if it is listed again it becomes active under the same id.
- `status` filter on the bank list: `active` (the default), `delisted` or `all`. `GET /api/countries/{country_code}/banks/{bank_id}` returns delisted banks too.
- `delisted_bank_count` in the country summary.
- Every bank has a `trading_name`: the name it trades under today, which is its `name` unless the register still lists an older one. The bank list's `q` search matches it too. Trading names are kept in a reviewed file per country; Nigeria's starts with OSCOTECH MFB (OSCT MFB), Pocket (Abeg Technologies), Nombank (Amucha), Aella (Flourish) and 9japay (Amegy).
- Nigeria: NIBSS codes for Quest Merchant Bank (formerly FBNQuest Merchant Bank, `060002`), Abeg Technologies (Pocket App, `100042`), Carbon (`100026`) and OSCT, now OSCOTECH (`090396`), bringing the total to 373.

### Changed

- The bank list returns only active banks unless `status` says otherwise, and `bank_count` counts only active banks. Nothing is delisted yet, so today's responses are unchanged apart from the new fields.
- `python -m src.refresh` reports banks as added, delisted, relisted or changed; it no longer removes any.
- `deploy/aws/provision.sh` needs `SITE_ADDRESS` set, and creates the instance in the CloudShell session's region unless `REGION` is set. `deploy/docker-compose.standalone.yml` needs `SITE_ADDRESS` too. The deployment guide and example settings use placeholder names.

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
