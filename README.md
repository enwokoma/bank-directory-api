# Bank Directory API

A Flask API that lists the licensed banks of each country, compiled from that country's official register, with the codes needed to send them bank transfers, and that tells which bank an account number belongs to where the number allows it. Countries are added one release at a time; each one comes with a script that rebuilds its data from the regulator's own list.

A public instance runs at [banks.globbapay.com](https://banks.globbapay.com/api-docs), and the data files can be used directly or with your own copy of the API: see [Use it in your project](#use-it-in-your-project).

## Coverage

| Country | Codes | Institutions | Bank types | Transfer codes | Sources |
| --- | --- | --- | --- | --- | --- |
| Nigeria | `NG` / `NGA` | 880 | commercial, merchant, non-interest, payment service, microfinance, primary mortgage, mobile money | 6-digit NIBSS (NIP) codes for 417 of them | [CBN: Financial Institutions](https://www.cbn.gov.ng/supervision/finstitutions.html), [CBN: Payment Service Providers](https://www.cbn.gov.ng/PaymentsSystem/PSPs.html), [NIBSS Instant Payment](https://nibss-plc.com.ng/nibss-instant-payment/) institution list |

`GET /api/countries` always shows the current list with each country's bank count and the date its data was retrieved. See [Notes on Nigeria's data](#notes-on-nigerias-data) for which banks have transfer codes. For Nigeria, `POST /api/detect-bank` also tells which banks a 10-digit account number can belong to, most likely first: see [Detect the bank from an account number](#detect-the-bank-from-an-account-number).

## Use it in your project

There are three ways, from least to most setup: call the public API, use the data file directly, or run the API yourself.

### Call the public API

`https://banks.globbapay.com` serves the latest release, deployed by the release workflow within minutes of its tag, with search, filters and lookups by code. Try it in the browser at [banks.globbapay.com/api-docs](https://banks.globbapay.com/api-docs), where the title shows which version it runs. What the changelog lists under Unreleased reaches it with the next release.

```js
const response = await fetch("https://banks.globbapay.com/api/countries/NG/banks?has=nibss_code");
const { banks } = await response.json();
// Institutions that can receive a NIP transfer, for a bank dropdown, e.g.
// { id: "access-bank", name: "Access Bank Plc", trading_name: "Access Bank Plc", type: "commercial",
//   status: "active", identifiers: { cbn_institution_id: "1", nibss_code: "000014", cbn_bank_code: "044" } }
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
| `https://raw.githubusercontent.com/enwokoma/bank-directory-api/v0.6.0/data/countries/NGA.json` | The file as released in v0.6.0, which never changes | Yes |
| `https://github.com/enwokoma/bank-directory-api/releases/latest/download/NGA.json` | The latest release's file, with a `SHA256SUMS` file next to it | No |
| `https://github.com/enwokoma/bank-directory-api/releases/download/v0.6.0/NGA.json` | The v0.6.0 release's file | No |

The `main` branch always has the newest data, reviewed before it is merged. The release download links suit servers, build scripts and the command line; browsers cannot fetch them from another site, because GitHub sends no CORS header for release downloads.

```js
// Always the latest data. To pin a release, replace "main" with its tag, such as "v0.6.0".
const url = "https://raw.githubusercontent.com/enwokoma/bank-directory-api/main/data/countries/NGA.json";
const { banks } = await (await fetch(url)).json();

// Institutions that can receive a NIP transfer, for a bank dropdown
const transferBanks = banks.filter((bank) => bank.status === "active" && bank.identifiers.nibss_code);
```

```python
import requests

# Always the latest data. To pin a release, replace "main" with its tag, such as "v0.6.0".
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
| `0.6` | The latest 0.6.x release |
| `0.6.0` | That exact release; pin one like this in production so upgrades are deliberate |

To build it from your own clone, for example after changing the code or refreshing the data, use the `compose.yaml` at the root of the repository:

```bash
git clone https://github.com/enwokoma/bank-directory-api.git
cd bank-directory-api
docker compose up --build
```

Either way it serves the API openly, with no rate limits or API keys, which suits your own machine or a private network. Settings are environment variables, such as `-e GUNICORN_WORKERS=2` for the number of worker processes (3 by default; 2 in `compose.yaml`). To serve it publicly with rate limits, API keys and HTTPS, see [docs/deploy.md](docs/deploy.md).

### Run it with Python

See the [step-by-step guide](#step-by-step-guide), or just [Setup](#setup) and [Running](#running).

## Step-by-step guide

The whole setup in order, from a clone to a public service. Each step links to the section with the details.

### 1. Install

You need git and Python 3.11 or newer. Clone the repository, create a virtual environment, and install the development dependencies, which are the runtime ones plus ruff, mypy and pytest:

```bash
git clone https://github.com/enwokoma/bank-directory-api.git
cd bank-directory-api
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

### 2. Check the setup

Run the checks CI runs. All four pass on a fresh clone:

```bash
ruff format --check .
ruff check .
mypy
pytest
```

### 3. Start the API and try it

```bash
python app.py
```

Open `http://localhost:5006/api-docs` for Swagger UI, or call the endpoints directly:

```bash
curl http://localhost:5006/api/countries
curl "http://localhost:5006/api/countries/NG/banks?has=nibss_code&limit=5"
curl "http://localhost:5006/api/countries/NG/banks?q=moniepoint"
curl http://localhost:5006/api/countries/NG/banks/access-bank
curl "http://localhost:5006/api/detect-bank?account_number=0016563228&limit=3"
```

The last one ranks the banks an account number can belong to. [Detect the bank from an account number](#detect-the-bank-from-an-account-number) explains the answer and how to use it in a transfer flow.

### 4. Use it from your application

Call your own copy, call the public instance, or read the data file straight from GitHub: see [Use it in your project](#use-it-in-your-project). Cache `GET` answers for an hour and revalidate with the `ETag`. For a transfer flow, run bank detection with the copied text as `hint`, then your payment provider's name enquiry on the recommended candidates in order, and remember what resolved.

### 5. Refresh the data

The data files are generated, reviewed and committed, never fetched at request time. To bring Nigeria's up to date:

```bash
cp .env.example .env            # optional: the NIP list settings, for the NIBSS codes
python -m src.refresh NGA --verbose
git diff data/countries/NGA.json
```

Review the diff and the report the command prints, then commit the file. Without `.env`, the NIBSS codes already in the file are kept. [Refreshing data](#refreshing-data) has the details, including how to combine several relayed NIP lists. Every Monday a workflow runs the same refresh and opens a pull request when a source changed, so most refreshes need only a review (see [Scheduled refreshes](#scheduled-refreshes)).

### 6. Maintain the reviewed files

Four files under `src/countries/nigeria/` hold what the sources cannot say, and the refresh applies them on every run:

| File | Maps | Add an entry when |
| --- | --- | --- |
| `nibss_code_matches.json` | Register name to NIBSS code | The register and the NIP list spell a bank's name differently |
| `trading_names.json` | Register name to trading name | A bank trades under a name the register has not caught up with |
| `cbn_bank_codes.json` | Register name to CBN bank code | A bank's CBN bank code is known and not listed yet; `python -m src.countries.nigeria.bank_code_sources` reports what payment providers' lists suggest |
| `account_detection.json` | Bank id to share, phone-number accounts, leading digits, aliases and other codes it issued numbers under | Your name-enquiry logs give a better estimate, or a bank gets a new short name |

Run the refresh after editing the first three, and the tests after editing any of them: the tests check that every entry names a bank in the data file.

### 7. Run it with Docker

Without installing Python, run the published image or build your clone:

```bash
docker run --rm -p 5006:5006 ghcr.io/enwokoma/bank-directory-api:latest   # the latest release
docker compose up --build                                                  # this checkout, refreshed data included
```

Both serve the API openly on `http://localhost:5006`; see [Run it with Docker](#run-it-with-docker).

### 8. Serve it publicly

A public server needs rate limits, API keys and HTTPS. Turn them on with the settings in [Hosted mode](#hosted-mode-rate-limits-and-api-keys), and follow [docs/deploy.md](docs/deploy.md) to run the API with Redis behind a proxy that serves HTTPS, on an AWS instance on its own or managed by Coolify. Once it runs, people get keys with `POST /api/keys/signup` (see [Getting a key](#getting-a-key)), and you manage them on the server with `python -m src.keys_admin`.

### 9. Release

Set the version in `src/__init__.py`, date the changelog, merge, and push a signed tag: see [Releases](#releases). The tag's workflow publishes the image, creates the GitHub release with the changelog section as its notes and the data files attached, and, once Coolify's webhook is configured, deploys it to the public instance.

### 10. Keep it healthy

Every push runs the checks and the Docker setups in CI, and a workflow compares the data files with their sources every Monday and opens a pull request with the refreshed data when they changed (see [Scheduled refreshes](#scheduled-refreshes)). `main` is protected: changes land through pull requests whose checks pass, and nothing is force-pushed or deleted, so a release is always cut from a state CI has run.

CI also scans the built image for known vulnerabilities, CodeQL scans the code on every change to `main`, and Dependabot proposes dependency updates every Monday (see [Development checks](#development-checks)). Once the repository has the `PUBLIC_SITE_URL` variable (see [docs/deploy.md](docs/deploy.md#deploying-releases-automatically)), a workflow fetches the public instance's `/` and `/apispec_1.json` every hour and, when either does not answer 200 within 20 seconds, opens an issue titled "Public instance is down", or adds the details to the open one; close it once the site is back. That is a coarse check: one request an hour from GitHub's runners, which can start a scheduled run late. For alerting, point an external monitor such as [UptimeRobot](https://uptimerobot.com) or [Better Stack](https://betterstack.com/uptime) at `/` as well; it checks every few minutes and notifies you at once.

## How the data works

Bank data is not fetched when a request comes in. Each country has a JSON file in `data/countries/` (for example `data/countries/NGA.json`) that is generated from its sources, reviewed as an ordinary git diff, and committed. The API loads every file at startup and refuses to start if one fails validation: unknown bank types, malformed or duplicated codes, and unsorted banks are all rejected.

A bank stays in its file after the regulator stops listing it, with `status` set to `delisted`, so stored ids and codes keep resolving. The file's git history shows when each bank was delisted. If the regulator lists it again, it becomes active again under the same id.

Serving the API needs no API keys, keeps working when a regulator's website is down, and makes every change to a country's bank list visible in the git history. The files can also be used directly without running the API.

Most sources are public web pages. Nigeria's transfer codes are the exception: NIBSS serves its institution list only to connected institutions, so refreshing the codes needs access to an API that relays it (see [Nigeria's NIBSS codes](#nigerias-nibss-codes)).

A scheduled workflow compares the committed files with their sources every Monday. When a source has changed, it refreshes the country's file and opens a pull request with the result and the refresh's report, so the change needs only a review (see [Scheduled refreshes](#scheduled-refreshes)). It checks Nigeria's NIBSS codes only when the repository has the NIP list settings as secrets.

## Project structure

```text
bank-directory-api/
  app.py                  Flask app factory, Swagger UI, caching and CORS headers
  data/countries/         One generated JSON file per country
  src/
    __init__.py           The version, used by Swagger UI and the refresh's User-Agent
    api/
      routes.py           Country, bank and detect-bank routes
      schemas.py          Swagger definitions of every response, with examples
      access.py           Rate limits and API key checks (hosted mode)
      keys.py             GET /api/keys/me
      signup.py           API key sign-up by email
    core/
      dataset.py          Loads and validates the country data files
      detection.py        Shape of a bank detection, and each country's detector
      settings.py         Settings read from environment variables
      api_keys.py         API keys and sign-up tokens in SQLite, stored as hashes
      email.py            Sign-up emails through Amazon SES
      cleaning.py         Whitespace cleanup and id slugs used by refresh modules
      trading_names.py    Adds reviewed trading names to register records
      source_client.py    Polite, retrying HTTP client for sources
    countries/
      profile.py          Country profile shape
      registry.py         Registered countries, looked up by alpha-2 or alpha-3 code
      nigeria/
        profile.py        Nigeria's bank types, identifier schemes and code formats
        refresh.py        Reads the CBN register and adds NIBSS and CBN bank codes
        nuban.py          NUBAN check digit arithmetic
        detection.py      Ranks the banks an account number can belong to
        account_detection.json
                          Reviewed shares, phone-number wallets, leading digits and aliases per bank
        cbn_bank_codes.py Adds reviewed CBN bank codes to register records
        cbn_bank_codes.json
                          Reviewed CBN bank codes, which NUBAN check digits are computed from
        mobile_money.py   Reads the CBN's licensed mobile money operators
        nip.py            Reads the NIBSS Instant Payment institution list
        nibss_codes.py    Matches banks to NIBSS codes
        nibss_code_matches.json
                          Reviewed matches for names the lists spell differently
        trading_names.json
                          Reviewed names banks trade under where the register has an older one
    refresh.py            `python -m src.refresh` command
    keys_admin.py         `python -m src.keys_admin`: list, issue and revoke API keys
  Dockerfile              The API's image, served by gunicorn (gunicorn.conf.py)
  compose.yaml            Runs the API on your own machine with Docker Compose
  deploy/                 Docker Compose with Redis (and optionally Caddy), a Caddy block and example settings for a public server
    aws/provision.sh      Sets up a dedicated EC2 instance from AWS CloudShell
    coolify/docker-compose.yml  The API as a Coolify service, using the published image
  docs/deploy.md          How to run it as a public service on AWS: on its own, or managed by Coolify
  scripts/
    create-release.sh     Creates a release from its changelog section and attaches each country's data file; the tag workflow runs it
  tests/                  Tests, with saved samples of real source responses in fixtures/
  .env.example            Settings for refreshing NIBSS codes (copy to .env)
  .github/workflows/
    python-test.yml       Formatting, lint, types and tests on every push, then gunicorn and Docker checks
    data-check.yml        Monday check that the data files match their sources; opens a pull request with the refresh when they do not
    release-image.yml     Publishes the image, creates the GitHub release and deploys the public instance on each release tag
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

The examples call a local copy at `http://localhost:5006`; the public API answers the same paths at `https://banks.globbapay.com`. Swagger UI lists every endpoint at `/api-docs`. The Swagger 2.0 spec behind it, at `/apispec_1.json`, describes every response with a schema (`Bank`, `BankList`, `Detection`, `Error` and the others under `definitions`) and an example, so a typed client can be generated from it with the usual OpenAPI tools.

Country codes are ISO 3166-1 alpha-2 or alpha-3 codes in any case: `NG`, `ng`, `NGA` and `nga` all work.

Successful responses have `"success": true`. Errors have `"success": false` and a `message`, with status 400 for a bad parameter, 404 for an unknown country, bank or route, and in hosted mode 401 for a bad API key and 429 for too many requests:

```json
{
  "success": false,
  "message": "Unknown identifier scheme swift for Nigeria. Use one of: cbn_institution_id, nibss_code, cbn_bank_code."
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
      "retrieved_on": "2026-10-21"
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
    "retrieved_on": "2026-10-21",
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
      },
      {
        "code": "cbn_bank_code",
        "description": "CBN bank code, from which NUBAN account numbers' check digits are computed and which payment providers use as the bank code: 3 digits for banks (058 for GTBank), 5 for other financial institutions (50515 for Moniepoint)"
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
        "name": "Central Bank of Nigeria: microfinance bank codes",
        "url": "https://www.cbn.gov.ng/Out/2014/OFISD/MFB%20Codes.pdf"
      },
      {
        "name": "Paystack: bank list (CBN bank codes)",
        "url": "https://paystack.com/docs/api/miscellaneous/#bank"
      },
      {
        "name": "NIBSS Instant Payment (NIP) institution list",
        "url": "https://nibss-plc.com.ng/nibss-instant-payment/"
      }
    ],
    "bank_detection": true
  }
}
```

### List a country's banks

```http
GET /api/countries/{country_code}/banks
```

Query parameters, all optional:

- `status`: `active` (the default) for banks the regulator lists today, `delisted` for banks it no longer lists, or `all` for both. It applies to every other filter, identifier lookups included.
- `q`: match banks whose name, trading name or id contains this text, ignoring case, accents and extra spaces, so `q=nombank` finds the bank the register still calls Amucha Microfinance Bank
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
      "trading_name": "Zenith Bank Plc",
      "type": "commercial",
      "status": "active",
      "identifiers": {
        "cbn_institution_id": "24",
        "nibss_code": "000015",
        "cbn_bank_code": "057"
      }
    }
  ]
}
```

`total` counts every match; `banks` holds the requested page. Banks are sorted by name.

A bank transfer dropdown for Nigeria needs only the institutions with a NIBSS code (417 today), which includes mobile money operators such as OPay and PalmPay:

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
    "trading_name": "Access Bank Plc",
    "type": "commercial",
    "status": "active",
    "identifiers": {
      "cbn_institution_id": "1",
      "nibss_code": "000014",
      "cbn_bank_code": "044"
    }
  }
}
```

### Detect the bank from an account number

```http
GET  /api/detect-bank?account_number=0123456789
POST /api/detect-bank
GET  /api/countries/{country_code}/detect-bank?account_number=0123456789
POST /api/countries/{country_code}/detect-bank
```

A Nigerian account number does not name its bank, but its last digit is a check digit that the CBN's NUBAN standard computes from the first nine digits and the issuing institution's CBN bank code. So the number can be tested against every institution on NIP: an institution whose code gives a different digit cannot have issued it, which rules out about nine in ten. The rest are ranked, and each comes with a `confidence`, the estimated probability that it is the right one, from:

- how common the institution is as a transfer destination: reviewed estimates for the well-known ones and a default per bank type for the rest;
- whether the number looks like a Nigerian mobile number. OPay, PalmPay, Moniepoint, Paga and the payment service banks give customers their phone number as account number, which does not follow NUBAN, so those institutions are never ruled out, and a number starting with 70, 80, 81, 90 or 91 counts strongly for them;
- leading digits some banks are known to use, applied softly: Guaranty Trust Bank's account numbers all start with 0, Fidelity's with 4, 5 or 6;
- the `hint`, the text the number was copied with. An institution it names is put first whatever the number says, and stays in the list even when its check digit fails.

Parameters, as query parameters for `GET` or a JSON object for `POST`:

- `account_number` (required): the 10 digits. Spaces and dashes are ignored, and a mobile number written in full, `08012345678` or `+2348012345678`, is read as the wallet account number it stands for. In JSON, send it as a string, so leading zeros survive.
- `hint`: text copied along with the number, at most 200 characters, for example `GTBank 0123456789 John Doe`.
- `type`: comma-separated bank types to consider, for example `commercial,mobile_money`.
- `limit`: return at most this many candidates, 1 to 100 (default 10). `total_candidates` always counts every one.
- `coverage`: how sure the `recommended` block should be of holding the right institution, 0.5 to 0.99 (default 0.9). Candidates are recommended from the top until their confidences add up to it, at most five of them.
- `country`, on `/api/detect-bank` only: `NG` or `NGA`. Optional while Nigeria is the only country with detection.

```bash
curl -X POST http://localhost:5006/api/detect-bank \
  -H "Content-Type: application/json" -d '{"account_number": "0016563228", "limit": 3}'
```

```json
{
  "success": true,
  "country": { "alpha2": "NG", "alpha3": "NGA", "name": "Nigeria" },
  "account_number": "0016563228",
  "looks_like_phone_number": false,
  "best_guess": { "...": "the first candidate, repeated" },
  "recommended": {
    "coverage": 0.9,
    "confidence": 0.9063,
    "candidates": [ { "...": "the first two candidates, repeated" } ]
  },
  "candidates": [
    {
      "confidence": 0.6678,
      "reasons": ["check_digit", "account_prefix"],
      "institution_code": "000058",
      "check_digit_valid": true,
      "bank": {
        "id": "guaranty-trust-bank",
        "name": "Guaranty Trust Bank Plc",
        "trading_name": "Guaranty Trust Bank Plc",
        "type": "commercial",
        "status": "active",
        "identifiers": { "cbn_institution_id": "8", "nibss_code": "000013", "cbn_bank_code": "058" }
      }
    },
    { "confidence": 0.2385, "reasons": ["check_digit"], "institution_code": "950515", "check_digit_valid": true, "bank": { "id": "moniepoint-mfb", "...": "..." } },
    { "confidence": 0.0358, "reasons": ["check_digit"], "institution_code": "000070", "check_digit_valid": true, "bank": { "id": "fidelity-bank", "...": "..." } }
  ],
  "total_candidates": 44,
  "limit": 3
}
```

Each candidate carries:

| Field | Meaning |
| --- | --- |
| `confidence` | The estimated probability that this is the right institution. The confidences of all candidates, not only the returned ones, add up to 1; a candidate whose confidence rounds to 0 is left out. |
| `reasons` | The evidence for it, strongest first: `hint` (the hint names it), `phone_number_account` (the number looks like a mobile number and the institution issues those), `check_digit` (the check digit is the one its code gives), `account_prefix` (the number starts with digits it is known to use). An empty list means nothing counts for it, but nothing rules it out either: it issues account numbers outside NUBAN. |
| `institution_code` | The 6-digit code the check digit was tested with: `000` and the 3-digit CBN bank code for banks, `9` and the 5-digit code for other financial institutions, or the NIBSS code for institutions whose CBN bank code is not known. |
| `check_digit_valid` | Whether the number's check digit is the one that code gives. |
| `bank` | The bank as `GET /api/countries/{country_code}/banks/{bank_id}` returns it, with the `nibss_code` to send the transfer with. |

The `recommended` block holds the candidates to try first: taken from the top until their confidences add up to `coverage`, and never more than five, so an unambiguous number recommends one or two while an ambiguous one still gives a short list. Its `confidence` is the probability that the right institution is among them. The default of 0.9 suits a transfer screen that suggests a bank and lets the user change it: the suggestion is right most of the time and the list stays short. For a flow that runs name enquiry itself, a higher value such as 0.99 recommends more candidates to try in order, which with the cap of five means every candidate still worth an enquiry. A threshold on each candidate's own confidence would do worse: it lets too many through when the number is unambiguous and too few when it is not.

A `GET` answer is cached like the other data, since it depends only on the input; a `POST` answer is not.

#### What the check digit can and cannot tell apart

Only the weighted sum of an institution's code modulo 10 matters, so the 417 institutions on NIP fall into ten groups of about 40, and a number valid for one member of a group is valid for all of them. The best-known institutions fall as follows:

| Group | Institutions |
| --- | --- |
| 0 | Access Bank, United Bank for Africa, First Bank |
| 2 | Keystone Bank, Jaiz Bank, Globus Bank, Carbon |
| 3 | Sterling Bank, Stanbic IBTC Bank |
| 5 | First City Monument Bank, Ecobank, TAJ Bank, FairMoney, VFD |
| 6 | Zenith Bank, Wema Bank, Standard Chartered Bank, Providus Bank |
| 7 | Union Bank, Polaris Bank |
| 8 | Unity Bank, Lotus Bank, Kuda |
| 9 | Guaranty Trust Bank, Fidelity Bank, Titan Trust Bank, Moniepoint |

Within a group, only the leading digits, the hint and, in the end, a name enquiry tell the members apart. The wallets whose account numbers are phone numbers appear in every group's answer regardless.

#### Getting to a near-certain answer

The number alone cannot single out one of 400 institutions: it carries one digit of information. What gets a transfer flow to the right bank nearly every time is using the ranking as the order in which to try things:

1. Send the whole text the number was copied from as `hint`. Copied bank details usually name the bank, and a named institution goes first.
2. Run your payment provider's name enquiry on the `recommended` candidates in order, and stop at the first that resolves; raise `coverage` to try more before giving up. The ranking exists to make the first try the likely one and to keep the number of tries small.
3. Remember what resolved. An account number together with the institution it resolved at is the best evidence there is: check your own record before calling this endpoint, and put that institution first when you have one.
4. Calibrate the reviewed file. `src/countries/nigeria/account_detection.json` holds, per bank id, the `share` of transfers the institution receives (on any scale), the fraction of its accounts that are phone numbers (`phone_number_accounts`), the leading digits its account numbers are known to use (`account_prefixes`) and the names people call it (`aliases`), with a default share per bank type for the rest. The shares and leading digits are estimates; your own name-enquiry logs will give better ones, and changing the file needs no code change.

The CBN bank codes the check digit is computed with come from a reviewed file too (see [CBN bank codes](#cbn-bank-codes)). An institution whose code is not in it is tested with its NIBSS code instead, which may be wrong, so such an institution can be missing from the list when it should be there. Adding its code to the file fixes that.

## Bank fields

| Field | Description |
| --- | --- |
| `id` | Slug made from the bank's name when it was first listed, for example `access-bank`. It stays the same when the bank is renamed, so it is safe to store. |
| `name` | The name exactly as the official register publishes it, including its capitalization. Only stray spaces and line breaks are removed. |
| `trading_name` | The name the bank trades under today. It is the same as `name` unless the register still lists an older one, for example `Nombank` for the register's Amucha Microfinance Bank Limited. It is always set, so show it where people pick a bank, such as a transfer dropdown. |
| `type` | One of the country's bank type codes, listed by `GET /api/countries/{country_code}`. |
| `status` | `active` while the regulator lists the bank, `delisted` once it no longer does: its licence was revoked, it merged into another bank, or it otherwise left the register. |
| `identifiers` | Codes for the bank under the schemes the country declares, listed by `GET /api/countries/{country_code}`. A scheme is left out when the bank has no code under it. |

Nigeria's identifier schemes:

| Scheme | Description |
| --- | --- |
| `cbn_institution_id` | The bank's record ID in the CBN register. Mobile money operators come from a different CBN page and have none. |
| `nibss_code` | The 6-digit code NIBSS uses for the institution in NIBSS Instant Payment (NIP) transfers, for example `000014` for Access Bank and `100004` for OPay. Payment providers' transfer APIs either take this code or list it next to their own, so it can be matched to any provider. Institutions that are not on NIP, which includes most small microfinance banks, have none. |
| `cbn_bank_code` | The CBN's own code for the institution, from which the check digit of its NUBAN account numbers is computed, and the code payment providers such as Paystack take as the bank code: 3 digits for banks, `058` for GTBank, and 5 for other financial institutions, `50515` for Moniepoint. It comes from a reviewed file, so institutions whose code is not known yet have none. |

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

### Scheduled refreshes

Every Monday the Data Freshness workflow (`.github/workflows/data-check.yml`) runs `python -m src.refresh all --check`. When a data file no longer matches its sources, the workflow runs the refresh itself, runs the checks CI runs (`ruff format --check .`, `ruff check .`, `mypy` and `pytest`) on the result, commits the data files on a branch named `data/refresh-YYYY-MM-DD` and opens a pull request against `main` whose description is the refresh's report: the banks added, delisted, listed again or changed, and any warning about the reviewed files. Bringing the data up to date then means reviewing the diff, fixing on that branch what the warnings point at, and merging. While such a pull request is open, the next Monday's run pushes a new refresh to its branch when the sources changed again, and posts the report as a comment, rather than opening a second one.

Running the workflow by hand from the Actions tab only reports, as before: a run that finds a difference, or cannot read a source, fails. Tick "Open or update a refresh pull request" to get the pull request without waiting for Monday, and run it on `main`, since the branch is cut from the ref the workflow runs on.

The pull request is opened with the workflow's own `GITHUB_TOKEN` unless the repository has a `DATA_REFRESH_TOKEN` secret. The two differ in what has to happen by hand:

- With `GITHUB_TOKEN`, the repository must allow it to open pull requests: under Settings > Actions > General > Workflow permissions, tick "Allow GitHub Actions to create and approve pull requests". Otherwise the run fails at that step, after pushing the branch, which the next run replaces. Pushes and pull requests made with this token also start no other workflow, so the Python Tests checks that `main` requires do not run on their own. The refresh job runs the same checks before committing, and the description says so, but to get the required checks you push a commit to the branch (an empty one will do: `git commit --allow-empty -m "ci: run the checks"`) or close and reopen the pull request.
- With a fine-grained personal access token stored as the `DATA_REFRESH_TOKEN` repository secret, the workflow pushes and opens the pull request as the token's owner, so the Python Tests workflow runs as for any pull request and the Actions setting above is not needed. Create the token under your GitHub settings (Developer settings > Personal access tokens > Fine-grained tokens) for this repository only, with the repository permissions Contents: Read and write and Pull requests: Read and write, and note its expiry: once it expires, the run fails at the push until the secret is replaced.

The workflow refreshes the NIBSS codes only when the repository has the NIP list settings as secrets, as the next section describes; without them the codes already in the file are kept, as locally. It never prints the endpoints or keys, and the report in the pull request names only banks, institutions and the settings' names.

### Nigeria's NIBSS codes

NIBSS does not publish its institution list openly; it serves it to connected institutions through NIP's `financialinstitutionlist` operation, and payment providers relay it to their API customers. To refresh the codes, copy `.env.example` to `.env` and set the URL of an API that returns the list, with its key and, if it is not `X-API-Key`, the header that carries the key. `.env` is ignored by git, and the refresh never prints the endpoints or keys, so they never reach the repository.

A relayed copy can leave institutions out, so up to five can be combined: the same setting names ending in `_2` to `_5` configure more endpoints, and the lists are merged by code. Paystack's bank list is one such relay: it returns the NIP code as `nip_sort_code` only when called as `https://api.paystack.co/bank?currency=NGN&include_nip_sort_code=true` (with `country=nigeria` instead of `currency=NGN` it leaves the field out), with the header set to `Authorization` and the key written as `Bearer sk_...`.

```bash
cp .env.example .env
python -m src.refresh NGA --verbose
```

Without these settings, the refresh keeps the codes already in the file and updates everything else.

With them, the command also prints a review report: every match with the institution's name in the NIP list (with `--verbose`), banks still without a code, and NIP institutions that matched no bank. A bank gets a code automatically only when its name matches exactly one NIP institution of a plausible type, and no other bank claims it. When the lists spell a name differently, add the bank's name exactly as the CBN publishes it, with its code, to `src/countries/nigeria/nibss_code_matches.json`, check that the code really belongs to that bank, and run the refresh again. A name mapped to `null` stays without a code. No code may belong to two banks; a data file where one does fails validation.

The scheduled check and refresh use the codes too when the repository has the same settings as secrets: `NIP_INSTITUTIONS_URL` and `NIP_INSTITUTIONS_API_KEY` (and `NIP_INSTITUTIONS_KEY_HEADER` if the header is not `X-API-Key`), plus the `_2` and `_3` versions for more lists. GitHub masks secret values in the logs.

### Trading names

Registers are slow to record renames, so a bank's `name` can be one it no longer uses. To give it the name it trades under, add the bank's name exactly as the register publishes it, with its trading name, to `src/countries/nigeria/trading_names.json` and run the refresh again. The refresh warns about an entry that names no bank in the register, and about one whose trading name the register now uses itself; remove such entries.

### CBN bank codes

The CBN gives every bank a 3-digit code and every other financial institution a 5-digit one. NUBAN account numbers' check digits are computed from it, and payment providers such as Paystack use it as the bank code, but the CBN's register does not show it, so `src/countries/nigeria/cbn_bank_codes.json` keeps a reviewed copy: the bank's name exactly as the register publishes it, mapped to its code. The microfinance banks' codes come from the CBN's own list of them (`MFB Codes.pdf` under its OFISD publications), matched to the register by name where the name is unique in both lists; the other institutions' come from Paystack's bank list, which carries both this code and the NIBSS code, checked against published lists for the deposit money banks. On the microfinance banks both sources cover, the two agree on every 5-digit code. The refresh applies the file every time and needs no settings for it; it warns about an entry that names no bank in the register, and no code may belong to two banks. To add a bank, confirm its code with the CBN's list or a payment provider's, add the entry, and run the refresh again. Institutions without an entry are tested with their NIBSS code when detecting a bank from an account number.

`python -m src.countries.nigeria.bank_code_sources` reads the bank lists of Paystack (public), Monnify and Flutterwave (with the credentials in `.env`, see `.env.example`) and reports the institutions whose code the reviewed file lacks but a provider gives, the reviewed codes a provider disagrees with, and how many every provider confirms. It changes nothing: a 3-digit code from a provider is often a legacy NIBSS code rather than the CBN's, so each suggestion is for review.

## Adding a country

1. Find an official, public source for the country's licensed banks, usually the central bank or banking regulator. Do not use sources whose terms forbid redistribution, such as the SWIFT BIC directory or paid sort-code directories.
2. Create `src/countries/<country>/profile.py` with a `CountryProfile`: ISO codes, name, currency, the bank types the regulator licenses, the identifier schemes the source provides, and a pattern for each scheme's values. Banks keep their ids between refreshes through any shared identifier, or failing that their exact name.
3. Create `src/countries/<country>/refresh.py` with a `fetch_dataset(client, previous_banks)` function that returns `{"sources": [...], "banks": [...]}`, where each bank has `name`, `type` and `identifiers`, and `trading_name` if the country keeps reviewed trading names (see `src/core/trading_names.py`); a bank without one trades under its `name`. `previous_banks` holds the banks already in the file, for values a source cannot supply on a given run. Use `SourceClient` for requests and `clean_text` for names.
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

CI runs the same checks on Python 3.11, 3.12 and 3.13 for every push, then serves the app with gunicorn and queries it. `main` only takes pull requests whose checks have passed. It also builds the image and runs each Docker setup: the public one with a real Redis, checking rate limits, keys, logs and that nothing logs an error; the same with Caddy in front; the Coolify Compose file; and the local `compose.yaml`. Tests never read your `.env`, call a real NIP list or send email.

CI then scans the image that `compose.yaml` built with [Trivy](https://trivy.dev) for known vulnerabilities in its system and Python packages. A high or critical one that has a fix fails the run; one without a fix yet is left out. To run the scan yourself, build the image and point Trivy's own image at it through the Docker socket:

```bash
docker compose build
docker run --rm --volume /var/run/docker.sock:/var/run/docker.sock \
  aquasec/trivy:0.76.1 image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 bank-directory-api:local
```

The first run downloads Trivy's vulnerability database, which takes a minute. [CodeQL](https://codeql.github.com) scans the Python code and the workflows on every change to `main` and once a week, with its findings under the repository's Security tab, and [Dependabot](.github/dependabot.yml) proposes new versions of the Python packages, the actions and the base image every Monday, minor and patch updates of Python packages together in one pull request.

## Notes on Nigeria's data

- The banks come from the JSON endpoints behind the CBN's Financial Institutions pages: one per licence category.
- Mobile money operators come from the CBN's Payment Service Providers page, which lists 17. The register's own mobile money list is shorter and leaves out OPay. Each operator's NIBSS code is the one its wallets use on NIP.
- 417 of the 880 institutions have a NIBSS code: all 28 commercial banks, all 5 payment service banks, 5 of 6 non-interest banks, all 5 merchant banks, 24 of 33 primary mortgage banks, all 17 mobile money operators and 333 of 786 microfinance banks. Mint Microfinance Bank has none because it now trades as Mint - Finex MFB, whose code the register's FINEX MFB holds, and most microfinance banks without a code are not on NIP at all.
- 598 of the 880 institutions have a CBN bank code, 311 of the 417 on NIP: all 28 commercial banks, 4 of 5 merchant banks, all 5 non-interest banks, 16 of 24 primary mortgage banks, and 545 of 786 microfinance banks (258 of the 333 on NIP), whose codes come from the CBN's own list of microfinance bank codes, with a few confirmed through payment providers' lists where a licence changed hands (Advancly holds Biztrust's code, Letshego FBN Microfinance Bank's). The payment service banks and mobile money operators have none, since neither source gives one; bank detection tests those with their NIBSS code.
- Four early microfinance banks on NIP, Accion, Bosak, Chikum and FUT Minna, issued account numbers under 3-digit NIBSS codes (602, 650, 312 and 832) before the CBN's 5-digit ones, and payment providers such as Paystack still list them under those. Their `cbn_bank_code` is the CBN's; bank detection tests both codes, through `other_bank_codes` in `account_detection.json`.
- Names are matched to codes, not codes to names, so a bank renamed in one list but not the other keeps its code through a reviewed match. For example, the register's Amucha, Flourish and Amegy microfinance banks hold the codes NIP lists under their new names, Nombank, Aella and 9japay, and Quest Merchant Bank, Abeg Technologies, OSCT and Visual ICT hold the codes NIP lists as FBNQuest Merchant Bank, Pocket App, Oscotech MFB and TagPay.
- The CBN register lists a few microfinance banks twice under different record IDs, with the same name, town and licence date. Each name is kept once, with its lowest record ID.
- The register also has a per-bank detail endpoint with licence tier and website, but it fails for many banks and its websites are out of date, so it is not used.

## API stability

The version in `src/__init__.py`, which every release tag carries, says what may have changed between two releases:

- Within a minor version, responses only gain fields. Code that reads the API or the data file should ignore fields it does not know, and never reject a record for having one.
- Nothing is removed or renamed, in a response or in the data file, without a new major version and a notice in the changelog.
- Bank ids are stable. A bank keeps its id across refreshes and releases, and stays in the data as `delisted` when the regulator stops listing it, so the ids and codes you have stored keep resolving.
- The data file's shape, `data/countries/<CODE>.json` as the API serves it, is part of the API and follows the same rules.
- Breaking changes, including behaviour that changes without a field being removed, are announced under a **Breaking changes** heading at the top of the release's changelog entry and release notes, as the notes for release 0.4.0 did when the bank list began returning only active banks by default.

## Releases

Each release is tagged `vX.Y.Z` on GitHub, with its changes in [CHANGELOG.md](CHANGELOG.md) and every country's data file attached, and its image is published as `ghcr.io/enwokoma/bank-directory-api:X.Y.Z` for amd64 and arm64, also tagged `X.Y` and `latest`, with GitHub's attestation of where it was built (see [Verifying the image](docs/deploy.md#verifying-the-image)). The version lives in `src/__init__.py`.

To publish a release:

1. In a pull request, set the version in `src/__init__.py` and date the release's section in the changelog, `## X.Y.Z - YYYY-MM-DD`.
2. After merging, tag the merge commit and push the tag: `git tag -s vX.Y.Z -m "vX.Y.Z"`, then `git push origin vX.Y.Z`.
3. Done. The tag's workflow checks that the tag is signed, matches the version and has its changelog section, then builds and publishes the image, creates the GitHub release with that changelog section as its notes and the data files attached, and deploys it to the public instance through Coolify once the repository has the secrets described in [docs/deploy.md](docs/deploy.md#deploying-releases-automatically), checking that `/api-docs` shows the new version. Without them, deploy it by hand in Coolify.

The notes can be edited on GitHub afterwards. If the workflow's **Create the GitHub release** job failed, `scripts/create-release.sh vX.Y.Z` does its work from your machine: it creates the release unless it already exists, and attaches the data files as they were at the tag.

## Disclaimer

The data is compiled from public registers and relayed copies of the NIBSS institution list, and may lag behind them. It is not affiliated with or endorsed by any regulator or by NIBSS. Check the regulator's own list before relying on a bank's licence status. A NIBSS code only identifies the receiving institution: before sending money, confirm the recipient's account name through your payment provider's name enquiry. Bank detection ranks the institutions an account number can belong to; it is a suggestion to verify with name enquiry, never a reason to skip it.

## License

MIT. See [LICENSE](LICENSE).
