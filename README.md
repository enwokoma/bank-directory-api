# Bank Directory API

A Flask API that lists the licensed banks of each country, compiled from that country's official register, with the codes needed to send them bank transfers. Countries are added one release at a time; each one comes with a script that rebuilds its data from the regulator's own list.

A public instance runs at [banks.globbapay.com](https://banks.globbapay.com/api-docs), and the data files can be used directly or with your own copy of the API: see [Use it in your project](#use-it-in-your-project).

## Coverage

| Country | Codes | Institutions | Bank types | Transfer codes | Sources |
| --- | --- | --- | --- | --- | --- |
| Nigeria | `NG` / `NGA` | 880 | commercial, merchant, non-interest, payment service, microfinance, primary mortgage, mobile money | 6-digit NIBSS (NIP) codes for 371 of them | [CBN: Financial Institutions](https://www.cbn.gov.ng/supervision/finstitutions.html), [CBN: Payment Service Providers](https://www.cbn.gov.ng/PaymentsSystem/PSPs.html), [NIBSS Instant Payment](https://nibss-plc.com.ng/nibss-instant-payment/) institution list |

`GET /api/countries` always shows the current list with each country's bank count and the date its data was retrieved. See [Notes on Nigeria's data](#notes-on-nigerias-data) for which banks have transfer codes.

## Use it in your project

There are three ways, from least to most setup: call the public API, use the data file directly, or run the API yourself.

### Call the public API

`https://banks.globbapay.com` serves the latest release, with search, filters and lookups by code. Try it in the browser at [banks.globbapay.com/api-docs](https://banks.globbapay.com/api-docs).

```js
const response = await fetch("https://banks.globbapay.com/api/countries/NG/banks?has=nibss_code");
const { banks } = await response.json();
// Institutions that can receive a NIP transfer, for a bank dropdown, e.g.
// { id: "access-bank", name: "Access Bank Plc", type: "commercial", status: "active",
//   identifiers: { cbn_institution_id: "1", nibss_code: "000014" } }
```

```python
import requests

response = requests.get("https://banks.globbapay.com/api/countries/NG/banks", params={"has": "nibss_code"}, timeout=10)
transfer_banks = response.json()["banks"]
```

Without a key, each IP address can make 60 requests an hour and 300 a day, which is plenty for a web page that calls it from its visitors' browsers. A server that calls it more often should [get a free key](#getting-a-key), which allows 120 requests a minute and 20,000 a day; keys belong on servers, not in browser code. Responses can be cached for an hour. See [Endpoints](#endpoints) for everything the API can do.

### Use the data file

Each country's data is one JSON file, the same one the API serves. Fetch it from GitHub, either always the latest or pinned to a release:

| URL | Gives you | From a browser |
| --- | --- | --- |
| `https://raw.githubusercontent.com/enwokoma/bank-directory-api/main/data/countries/NGA.json` | Always the latest data | Yes |
| `https://raw.githubusercontent.com/enwokoma/bank-directory-api/v0.3.4/data/countries/NGA.json` | The file as released in v0.3.4, which never changes | Yes |
| `https://github.com/enwokoma/bank-directory-api/releases/latest/download/NGA.json` | The latest release's file, with a `SHA256SUMS` file next to it | No |
| `https://github.com/enwokoma/bank-directory-api/releases/download/v0.3.4/NGA.json` | The v0.3.4 release's file | No |

The `main` branch always has the newest data, reviewed before it is merged. The release download links suit servers, build scripts and the command line; browsers cannot fetch them from another site, because GitHub sends no CORS header for release downloads.

```js
// Always the latest data. To pin a release, replace "main" with its tag, such as "v0.3.4".
const url = "https://raw.githubusercontent.com/enwokoma/bank-directory-api/main/data/countries/NGA.json";
const { banks } = await (await fetch(url)).json();

// Institutions that can receive a NIP transfer, for a bank dropdown
const transferBanks = banks.filter((bank) => bank.status === "active" && bank.identifiers.nibss_code);
```

```python
import requests

# Always the latest data. To pin a release, replace "main" with its tag, such as "v0.3.4".
url = "https://raw.githubusercontent.com/enwokoma/bank-directory-api/main/data/countries/NGA.json"
banks = requests.get(url, timeout=10).json()["banks"]
transfer_banks = [bank for bank in banks if bank["status"] == "active" and "nibss_code" in bank["identifiers"]]
```

To download the latest release's file and check it:

```bash
curl -LO https://github.com/enwokoma/bank-directory-api/releases/latest/download/NGA.json
curl -LO https://github.com/enwokoma/bank-directory-api/releases/latest/download/SHA256SUMS
shasum -a 256 -c SHA256SUMS
```

Each file has `country`, `retrieved_on`, `sources` and `banks`; each bank has the fields described in [Bank fields](#bank-fields), and its `id` stays the same between releases. The file also keeps banks the regulator no longer lists, with `status` set to `delisted`, so filter on `status` as the examples do.

Following `main` or `latest` picks up new data without changing your code; pinning a release means the data only changes when you upgrade. Either way, GitHub's links are not meant for production traffic: there is no uptime guarantee, and heavy use gets rate limited. Bundle the file with your app, or download it on a schedule and cache it, rather than fetching it on every request.

### Run it with Docker

The image is published for amd64 and arm64, so it runs on most machines, Apple silicon included:

```bash
docker run --rm -p 5006:5006 ghcr.io/enwokoma/bank-directory-api:latest
```

Then open `http://localhost:5006/api-docs`. To keep it running in the background and start it again after a reboot, use `docker run --detach --name bank-directory-api --restart unless-stopped -p 5006:5006 ghcr.io/enwokoma/bank-directory-api:latest`.

| Tag | Gives you |
| --- | --- |
| `latest` | The latest release |
| `0.3` | The latest 0.3.x release |
| `0.3.4` | That exact release; pin one like this in production so upgrades are deliberate |

To build it from your own clone, for example after changing the code or refreshing the data, use the `compose.yaml` at the root of the repository:

```bash
git clone https://github.com/enwokoma/bank-directory-api.git
cd bank-directory-api
docker compose up --build
```

Either way it serves the API openly, with no rate limits or API keys, which suits your own machine or a private network. Settings are environment variables, such as `-e GUNICORN_WORKERS=2` for the number of worker processes (3 by default; 2 in `compose.yaml`). To serve it publicly with rate limits, API keys and HTTPS, see [docs/deploy.md](docs/deploy.md).

### Run it with Python

See [Setup](#setup) and [Running](#running).

## How the data works

Bank data is not fetched when a request comes in. Each country has a JSON file in `data/countries/` (for example `data/countries/NGA.json`) that is generated from its sources, reviewed as an ordinary git diff, and committed. The API loads every file at startup and refuses to start if one fails validation: unknown bank types, malformed or duplicated codes, and unsorted banks are all rejected.

A bank stays in its file after the regulator stops listing it, with `status` set to `delisted`, so stored ids and codes keep resolving. The file's git history shows when each bank was delisted. If the regulator lists it again, it becomes active again under the same id.

Serving the API needs no API keys, keeps working when a regulator's website is down, and makes every change to a country's bank list visible in the git history. The files can also be used directly without running the API.

Most sources are public web pages. Nigeria's transfer codes are the exception: NIBSS serves its institution list only to connected institutions, so refreshing the codes needs access to an API that relays it (see [Nigeria's NIBSS codes](#nigerias-nibss-codes)).

A scheduled workflow compares the committed files with their sources every Monday. When it fails, a source has changed and the country needs a refresh (see [Refreshing data](#refreshing-data)). It checks Nigeria's NIBSS codes only when the repository has the NIP list settings as secrets.

## Project structure

```text
bank-directory-api/
  app.py                  Flask app factory, Swagger UI, caching and CORS headers
  data/countries/         One generated JSON file per country
  src/
    __init__.py           The version, used by Swagger UI and the refresh's User-Agent
    api/
      routes.py           Country and bank routes
      access.py           Rate limits and API key checks (hosted mode)
      keys.py             GET /api/keys/me
      signup.py           API key sign-up by email
    core/
      dataset.py          Loads and validates the country data files
      settings.py         Settings read from environment variables
      api_keys.py         API keys and sign-up tokens in SQLite, stored as hashes
      email.py            Sign-up emails through Amazon SES
      cleaning.py         Whitespace cleanup and id slugs used by refresh modules
      source_client.py    Polite, retrying HTTP client for sources
    countries/
      profile.py          Country profile shape
      registry.py         Registered countries, looked up by alpha-2 or alpha-3 code
      nigeria/
        profile.py        Nigeria's bank types, identifier schemes and code formats
        refresh.py        Reads the CBN register and adds NIBSS codes
        mobile_money.py   Reads the CBN's licensed mobile money operators
        nip.py            Reads the NIBSS Instant Payment institution list
        nibss_codes.py    Matches banks to NIBSS codes
        nibss_code_matches.json
                          Reviewed matches for names the lists spell differently
    refresh.py            `python -m src.refresh` command
    keys_admin.py         `python -m src.keys_admin`: list, issue and revoke API keys
  Dockerfile              The API's image, served by gunicorn (gunicorn.conf.py)
  compose.yaml            Runs the API on your own machine with Docker Compose
  deploy/                 Docker Compose with Redis (and optionally Caddy), a Caddy block and example settings for a public server
    aws/provision.sh      Sets up a dedicated EC2 instance from AWS CloudShell
    coolify/docker-compose.yml  The API as a Coolify service, using the published image
  docs/deploy.md          How to run it as a public service on AWS: on its own, or managed by Coolify
  scripts/
    upload-release-assets.sh  Attaches each country's data file to a GitHub release
  tests/                  Tests, with saved samples of real source responses in fixtures/
  .env.example            Settings for refreshing NIBSS codes (copy to .env)
  .github/workflows/
    python-test.yml       Formatting, lint, types and tests on every push, then gunicorn and Docker checks
    data-check.yml        Monday check that the data files match their sources
    release-image.yml     Publishes the image to ghcr.io/enwokoma/bank-directory-api on each release tag
  CHANGELOG.md            What each release added or changed
```

## Setup

To run the API without installing Python, use [Docker](#run-it-with-docker). To work on it with Python, you need Python 3.11 or newer:

```bash
git clone https://github.com/enwokoma/bank-directory-api.git
cd bank-directory-api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

On Windows, activate the environment with `.venv\Scripts\activate`. To only serve the API, `requirements.txt` is enough.

## Running

```bash
python app.py
```

The development server runs on `http://localhost:5006`, and Swagger UI is at `http://localhost:5006/api-docs`.

For production-style serving:

```bash
gunicorn --bind 0.0.0.0:5006 --workers 2 app:app
```

With no settings, the API serves its data openly, with no rate limits or keys. Before exposing it publicly, turn on [hosted mode](#hosted-mode-rate-limits-and-api-keys).

To serve it publicly with Redis, rate limits and HTTPS, see [docs/deploy.md](docs/deploy.md).

## Hosted mode: rate limits and API keys

Rate limits and API keys are off unless configured with environment variables:

| Setting | Effect |
| --- | --- |
| `RATE_LIMIT_STORAGE_URI` | Turns on rate limits, counted in this store, for example `redis://redis:6379/0`. |
| `ANONYMOUS_RATE_LIMIT` | Limits per client IP for requests without a key. Default `60 per hour;300 per day`. |
| `KEY_RATE_LIMIT` | Limits per API key. Default `120 per minute;20000 per day`. |
| `SIGNUP_RATE_LIMIT` | Limits per client IP on the sign-up endpoints. Default `10 per hour;30 per day`. |
| `API_KEY_DATABASE` | Turns on API keys, stored only as SHA-256 hashes in this SQLite file. |
| `PUBLIC_BASE_URL` | The API's public address, used in sign-up emails. |
| `SIGNUP_EMAIL_FROM` | Turns on self-service sign-up, with emails sent from this address through Amazon SES. Needs `API_KEY_DATABASE` and `PUBLIC_BASE_URL`; AWS credentials come from the usual sources, such as an EC2 instance role. |
| `AWS_REGION` | The Amazon SES region the sender is verified in. Without it, the region comes from boto3's own sources, such as `AWS_DEFAULT_REGION`. |
| `TRUSTED_PROXIES` | How many reverse proxies sit in front of the app, so the client address comes from `X-Forwarded-For`. |

With limits on, responses under `/api/` carry `X-RateLimit-Limit`, `X-RateLimit-Remaining` and `X-RateLimit-Reset`, and a request over the limit gets `429` with `Retry-After`:

```json
{
  "success": false,
  "message": "Rate limit exceeded: 60 per 1 hour. Try again later. An API key gives higher limits: POST /api/keys/signup."
}
```

Send a key in the `X-API-Key` header, or as `Authorization: Bearer <key>`, to be counted under the key's own, higher limit. An unknown or revoked key gets `401`. A key in the URL gets `400`, so keys stay out of access logs. Keys are meant for servers: a key in browser code is visible to anyone using the page.

### Getting a key

1. Ask for a key with your email address. For the public API, the host is `banks.globbapay.com`; for your own deployment, use its host:

   ```bash
   curl -X POST https://banks.globbapay.com/api/keys/signup \
     -H "Content-Type: application/json" -d '{"email": "you@example.com"}'
   ```

   The answer is the same whether or not the address already has a key, and an address gets at most three links a day. If the email can't be sent, the answer is `503` and the attempt doesn't count towards those three.

2. The email links to `GET /api/keys/verify?token=...`, a page with a button. The link works once, within 30 minutes.
3. The button shows the key once. Code can do this step with `POST /api/keys/verify` and `{"token": "..."}`, which returns `{"api_key": "bdk_..."}`.

Each address has one key: getting a new one revokes the old one, which is also how a lost key is replaced. `GET /api/keys/me` with your key shows its prefix, email, dates and rate limit.

### Managing keys

On the server, `python -m src.keys_admin` works on the `API_KEY_DATABASE` file:

```bash
python -m src.keys_admin list [EMAIL OR PREFIX]   # keys by prefix; the keys themselves are never stored
python -m src.keys_admin issue you@example.com    # issue a key by hand, printed once
python -m src.keys_admin revoke 12                # revoke a key by id
```

## Endpoints

The examples call a local copy at `http://localhost:5006`; the public API answers the same paths at `https://banks.globbapay.com`. Swagger UI lists every endpoint at `/api-docs`.

Country codes are ISO 3166-1 alpha-2 or alpha-3 codes in any case: `NG`, `ng`, `NGA` and `nga` all work.

Successful responses have `"success": true`. Errors have `"success": false` and a `message`, with status 400 for a bad query parameter, 404 for an unknown country, bank or route, and in hosted mode 401 for a bad API key and 429 for too many requests:

```json
{
  "success": false,
  "message": "Unknown identifier scheme swift for Nigeria. Use one of: cbn_institution_id, nibss_code."
}
```

`GET` responses under `/api/` carry `Cache-Control: public, max-age=3600` and an `ETag`, so clients can revalidate with `If-None-Match` and get `304 Not Modified`. They also allow cross-origin requests from any site. Every response carries `X-Content-Type-Options: nosniff`, and responses over HTTPS carry `Strict-Transport-Security`.

### Health check

```http
GET /
```

```json
{
  "status": "healthy",
  "message": "Bank Directory API is live"
}
```

### List countries

```http
GET /api/countries
```

```json
{
  "success": true,
  "countries": [
    {
      "alpha2": "NG",
      "alpha3": "NGA",
      "name": "Nigeria",
      "currency": "NGN",
      "bank_count": 880,
      "delisted_bank_count": 0,
      "retrieved_on": "2026-10-20"
    }
  ]
}
```

### Get a country

```http
GET /api/countries/{country_code}
```

Adds the country's bank types with a count for each, the identifier schemes its banks carry, and the sources its data comes from. `bank_count` and the counts per type cover active banks; `delisted_bank_count` counts the banks the regulator no longer lists:

```json
{
  "success": true,
  "country": {
    "alpha2": "NG",
    "alpha3": "NGA",
    "name": "Nigeria",
    "currency": "NGN",
    "bank_count": 880,
    "delisted_bank_count": 0,
    "retrieved_on": "2026-10-20",
    "bank_types": [
      { "code": "commercial", "name": "Commercial bank", "bank_count": 28 },
      { "code": "merchant", "name": "Merchant bank", "bank_count": 5 },
      { "code": "non_interest", "name": "Non-interest bank", "bank_count": 6 },
      { "code": "payment_service", "name": "Payment service bank", "bank_count": 5 },
      { "code": "microfinance", "name": "Microfinance bank", "bank_count": 786 },
      { "code": "mortgage", "name": "Primary mortgage bank", "bank_count": 33 },
      { "code": "mobile_money", "name": "Mobile money operator", "bank_count": 17 }
    ],
    "identifier_schemes": [
      {
        "code": "cbn_institution_id",
        "description": "Record ID in the Central Bank of Nigeria's financial institutions register"
      },
      {
        "code": "nibss_code",
        "description": "6-digit NIBSS Instant Payment (NIP) institution code, used to send bank transfers"
      }
    ],
    "sources": [
      {
        "name": "Central Bank of Nigeria: Financial Institutions",
        "url": "https://www.cbn.gov.ng/supervision/finstitutions.html"
      },
      {
        "name": "Central Bank of Nigeria: Payment Service Providers",
        "url": "https://www.cbn.gov.ng/PaymentsSystem/PSPs.html"
      },
      {
        "name": "NIBSS Instant Payment (NIP) institution list",
        "url": "https://nibss-plc.com.ng/nibss-instant-payment/"
      }
    ]
  }
}
```

### List a country's banks

```http
GET /api/countries/{country_code}/banks
```

Query parameters, all optional:

- `status`: `active` (the default) for banks the regulator lists today, `delisted` for banks it no longer lists, or `all` for both. It applies to every other filter, identifier lookups included.
- `q`: match banks whose name or id contains this text, ignoring case, accents and extra spaces
- `type`: one or more comma-separated bank type codes, for example `commercial,merchant`
- `limit`: return at most this many banks (1 to 1000); omit it to get every match
- `offset`: skip this many matching banks first
- `has`: one or more comma-separated identifier schemes every bank must have, for example `has=nibss_code` to list only institutions on NIP
- any identifier scheme of the country, for example `nibss_code=000014`, to find the bank with that code

```bash
curl "http://localhost:5006/api/countries/NG/banks?type=commercial&q=zenith"
```

```json
{
  "success": true,
  "country": {
    "alpha2": "NG",
    "alpha3": "NGA",
    "name": "Nigeria"
  },
  "total": 1,
  "offset": 0,
  "limit": null,
  "banks": [
    {
      "id": "zenith-bank",
      "name": "Zenith Bank Plc",
      "type": "commercial",
      "status": "active",
      "identifiers": {
        "cbn_institution_id": "24",
        "nibss_code": "000015"
      }
    }
  ]
}
```

`total` counts every match; `banks` holds the requested page. Banks are sorted by name.

A bank transfer dropdown for Nigeria needs only the institutions with a NIBSS code (371 today), which includes mobile money operators such as OPay and PalmPay:

```bash
curl "http://localhost:5006/api/countries/NG/banks?has=nibss_code"
```

To turn a code from a transfer back into a bank, including one the regulator no longer lists:

```bash
curl "http://localhost:5006/api/countries/NG/banks?nibss_code=090267&status=all"
```

### Get a bank

```http
GET /api/countries/{country_code}/banks/{bank_id}
```

Returns the bank whether it is active or delisted, so stored ids keep working.

```bash
curl http://localhost:5006/api/countries/NG/banks/access-bank
```

```json
{
  "success": true,
  "country": {
    "alpha2": "NG",
    "alpha3": "NGA",
    "name": "Nigeria"
  },
  "bank": {
    "id": "access-bank",
    "name": "Access Bank Plc",
    "type": "commercial",
    "status": "active",
    "identifiers": {
      "cbn_institution_id": "1",
      "nibss_code": "000014"
    }
  }
}
```

## Bank fields

| Field | Description |
| --- | --- |
| `id` | Slug made from the bank's name when it was first listed, for example `access-bank`. It stays the same when the bank is renamed, so it is safe to store. |
| `name` | The name exactly as the official register publishes it, including its capitalization. Only stray spaces and line breaks are removed. |
| `type` | One of the country's bank type codes, listed by `GET /api/countries/{country_code}`. |
| `status` | `active` while the regulator lists the bank, `delisted` once it no longer does: its licence was revoked, it merged into another bank, or it otherwise left the register. |
| `identifiers` | Codes for the bank under the schemes the country declares, listed by `GET /api/countries/{country_code}`. A scheme is left out when the bank has no code under it. |

Nigeria's identifier schemes:

| Scheme | Description |
| --- | --- |
| `cbn_institution_id` | The bank's record ID in the CBN register. Mobile money operators come from a different CBN page and have none. |
| `nibss_code` | The 6-digit code NIBSS uses for the institution in NIBSS Instant Payment (NIP) transfers, for example `000014` for Access Bank and `100004` for OPay. Payment providers' transfer APIs either take this code or list it next to their own, so it can be matched to any provider. Institutions that are not on NIP, which includes most small microfinance banks, have none. |

## Refreshing data

Rebuild a country's file from its sources, then review and commit the diff:

```bash
python -m src.refresh NGA
git diff data/countries/NGA.json
```

The command prints which banks were added, delisted, listed again or otherwise changed. Existing banks keep their ids, and banks the source no longer lists stay in the file as delisted rather than being removed. If a source fails or the new data does not pass validation, the file is left untouched.

| Option | Effect |
| --- | --- |
| `NGA` (or `NG`, or several codes) | Refresh those countries |
| `all` | Refresh every registered country |
| `--check` | Report whether the sources changed, without writing anything; exits with 1 if they did |
| `--verbose` | Also print details for reviewing, such as every NIBSS code match |
| `--data-dir PATH` | Read and write data files somewhere other than `data/countries/` |

The scheduled workflow runs `python -m src.refresh all --check`.

### Nigeria's NIBSS codes

NIBSS does not publish its institution list openly; it serves it to connected institutions through NIP's `financialinstitutionlist` operation, and payment providers relay it to their API customers. To refresh the codes, copy `.env.example` to `.env` and set the URL of an API that returns the list, with its key and, if it is not `X-API-Key`, the header that carries the key. `.env` is ignored by git, and the refresh never prints the endpoints or keys, so they never reach the repository.

A relayed copy can leave institutions out, so up to five can be combined: the same setting names ending in `_2` to `_5` configure more endpoints, and the lists are merged by code.

```bash
cp .env.example .env
python -m src.refresh NGA --verbose
```

Without these settings, the refresh keeps the codes already in the file and updates everything else.

With them, the command also prints a review report: every match with the institution's name in the NIP list (with `--verbose`), banks still without a code, and NIP institutions that matched no bank. A bank gets a code automatically only when its name matches exactly one NIP institution of a plausible type, and no other bank claims it. When the lists spell a name differently, add the bank's name exactly as the CBN publishes it, with its code, to `src/countries/nigeria/nibss_code_matches.json`, check that the code really belongs to that bank, and run the refresh again. A name mapped to `null` stays without a code. No code may belong to two banks; a data file where one does fails validation.

The scheduled check compares the codes too when the repository has the same settings as secrets: `NIP_INSTITUTIONS_URL` and `NIP_INSTITUTIONS_API_KEY` (and `NIP_INSTITUTIONS_KEY_HEADER` if the header is not `X-API-Key`), plus the `_2` versions for a second list. GitHub masks secret values in the logs.

## Adding a country

1. Find an official, public source for the country's licensed banks, usually the central bank or banking regulator. Do not use sources whose terms forbid redistribution, such as the SWIFT BIC directory or paid sort-code directories.
2. Create `src/countries/<country>/profile.py` with a `CountryProfile`: ISO codes, name, currency, the bank types the regulator licenses, the identifier schemes the source provides, and a pattern for each scheme's values. Banks keep their ids between refreshes through any shared identifier, or failing that their exact name.
3. Create `src/countries/<country>/refresh.py` with a `fetch_dataset(client, previous_banks)` function that returns `{"sources": [...], "banks": [...]}`, where each bank has `name`, `type` and `identifiers`. `previous_banks` holds the banks already in the file, for values a source cannot supply on a given run. Use `SourceClient` for requests and `clean_text` for names.
4. Register the profile in `src/countries/registry.py`.
5. Run `python -m src.refresh <CODE>` to generate the data file.
6. Add tests for the refresh module using saved samples of the source's real responses in `tests/fixtures/<country>/`, then run the checks below.
7. Add the country to the coverage table above and to the changelog.

## Development checks

```bash
ruff format --check .
ruff check .
mypy
pytest
```

CI runs the same checks on Python 3.11, 3.12 and 3.13 for every push, then serves the app with gunicorn and queries it. It also builds the image and runs each Docker setup: the public one with a real Redis, checking rate limits, keys, logs and that nothing logs an error; the same with Caddy in front; the Coolify Compose file; and the local `compose.yaml`. Tests never read your `.env`, call a real NIP list or send email.

## Notes on Nigeria's data

- The banks come from the JSON endpoints behind the CBN's Financial Institutions pages: one per licence category.
- Mobile money operators come from the CBN's Payment Service Providers page, which lists 17. The register's own mobile money list is shorter and leaves out OPay. Each operator's NIBSS code is the one its wallets use on NIP.
- 371 of the 880 institutions have a NIBSS code: 27 of 28 commercial banks, all 5 payment service banks, 4 of 6 non-interest banks, all 5 merchant banks, 22 of 33 primary mortgage banks, 15 of 17 mobile money operators and 293 of 786 microfinance banks. Tatum Bank and Summit Bank were not in any NIP list used, and most microfinance banks without a code are not on NIP at all.
- Names are matched to codes, not codes to names, so a bank renamed in one list but not the other keeps its code through a reviewed match. For example, the register's Amucha, Flourish and Amegy microfinance banks hold the codes NIP lists under their new names, Nombank, Aella and 9japay, and Quest Merchant Bank and Abeg Technologies hold the codes NIP still lists as FBNQuest Merchant Bank and Pocket App.
- The CBN register lists a few microfinance banks twice under different record IDs, with the same name, town and licence date. Each name is kept once, with its lowest record ID.
- The register also has a per-bank detail endpoint with licence tier and website, but it fails for many banks and its websites are out of date, so it is not used.

## Releases

Each release is tagged `vX.Y.Z` on GitHub, with its changes in [CHANGELOG.md](CHANGELOG.md) and every country's data file attached, and its image is published as `ghcr.io/enwokoma/bank-directory-api:X.Y.Z` for amd64 and arm64, also tagged `X.Y` and `latest`. The version lives in `src/__init__.py`.

To publish a release:

1. In a pull request, set the version in `src/__init__.py` and date the release in the changelog.
2. After merging, tag the merge commit and push the tag: `git tag -s vX.Y.Z -m "vX.Y.Z"`, then `git push origin vX.Y.Z`. The tag starts the image build.
3. Create the release: `gh release create vX.Y.Z --verify-tag --notes-file <notes>`.
4. Attach the data files as they were at the tag: `scripts/upload-release-assets.sh vX.Y.Z`.

## Disclaimer

The data is compiled from public registers and relayed copies of the NIBSS institution list, and may lag behind them. It is not affiliated with or endorsed by any regulator or by NIBSS. Check the regulator's own list before relying on a bank's licence status. A NIBSS code only identifies the receiving institution: before sending money, confirm the recipient's account name through your payment provider's name enquiry.

## License

MIT. See [LICENSE](LICENSE).
