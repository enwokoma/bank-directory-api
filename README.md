# Bank Directory API

A Flask API that lists the licensed banks of each country, compiled from that country's official register, with the codes needed to send them bank transfers. Countries are added one release at a time; each one comes with a script that rebuilds its data from the regulator's own list.

## Coverage

| Country | Codes | Banks | Bank types | Transfer codes | Sources |
| --- | --- | --- | --- | --- | --- |
| Nigeria | `NG` / `NGA` | 880 | commercial, merchant, non-interest, payment service, microfinance, primary mortgage, mobile money | 6-digit NIBSS (NIP) codes | [CBN: Financial Institutions](https://www.cbn.gov.ng/supervision/finstitutions.html), [CBN: Payment Service Providers](https://www.cbn.gov.ng/PaymentsSystem/PSPs.html), [NIBSS Instant Payment](https://nibss-plc.com.ng/nibss-instant-payment/) institution list |

`GET /api/countries` always shows the current list with each country's bank count and the date its data was retrieved.

## How the data works

Bank data is not fetched when a request comes in. Each country has a JSON file in `data/countries/` (for example `data/countries/NGA.json`) that is generated from the official source, reviewed as an ordinary git diff, and committed. The API loads every file at startup and refuses to start if one fails validation.

This keeps the API fast and free of API keys, keeps it working when a regulator's website is down, and makes every change to a country's bank list visible in the git history. The files can also be used directly without running the API.

A scheduled workflow compares the committed files with their sources every Monday. When it fails, a regulator's list has changed and the country needs a refresh (see [Refreshing data](#refreshing-data)).

## Project structure

```text
bank-directory-api/
  app.py                  Flask app, Swagger UI, caching and CORS headers
  data/countries/         One generated JSON file per country
  src/
    api/routes.py         HTTP routes
    core/
      dataset.py          Loads and validates the country data files
      cleaning.py         Whitespace cleanup and id slugs used by refresh modules
      source_client.py    Polite, retrying HTTP client for official sources
    countries/
      profile.py          Country profile shape
      registry.py         Registered countries, looked up by alpha-2 or alpha-3 code
      nigeria/
        profile.py        Nigeria's bank types and identifier schemes
        refresh.py        Reads the CBN register and adds NIBSS codes
        mobile_money.py   Reads the CBN's licensed mobile money operators
        nip.py            Reads the NIBSS Instant Payment institution list
        nibss_codes.py    Matches banks to NIBSS codes
        nibss_code_matches.json  Reviewed matches for names the lists spell differently
    refresh.py            `python -m src.refresh` command
  tests/
```

## Setup

Requires Python 3.11 or newer.

```bash
git clone https://github.com/enwokoma/bank-directory-api.git
cd bank-directory-api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

On Windows, activate the environment with `.venv\Scripts\activate`.

## Running

```bash
python app.py
```

The development server runs on `http://localhost:5006`, and Swagger UI is at `http://localhost:5006/api-docs`.

For production-style serving:

```bash
gunicorn --bind 0.0.0.0:5006 --workers 2 app:app
```

The API is read-only and needs no configuration or secrets. If you expose it publicly, put rate limiting in front of it at the proxy or load balancer.

## Endpoints

Country codes are ISO 3166-1 alpha-2 or alpha-3 codes in any case: `NG`, `ng`, `NGA` and `nga` all work.

Successful responses have `"success": true`. Errors have `"success": false` and a `message`, with status 400 for a bad query parameter and 404 for an unknown country, bank or route.

`GET` responses under `/api/` carry `Cache-Control: public, max-age=3600` and an `ETag`, so clients can revalidate with `If-None-Match` and get `304 Not Modified`. They also allow cross-origin requests from any site.

### Health check

```http
GET /
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
      "retrieved_on": "2026-10-14"
    }
  ]
}
```

### Get a country

```http
GET /api/countries/{country_code}
```

Adds the country's bank types with a count for each, the identifier schemes its banks carry, and the sources its data comes from.

### List a country's banks

```http
GET /api/countries/{country_code}/banks
```

Query parameters, all optional:

- `q`: match banks whose name or id contains this text, ignoring case, accents and extra spaces
- `type`: one or more comma-separated bank type codes, for example `commercial,merchant`
- `limit`: return at most this many banks (1 to 1000); omit it to get every match
- `offset`: skip this many matching banks first
- `has`: one or more comma-separated identifier schemes every bank must have, for example `has=nibss_code` to list only banks that can receive transfers
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
      "identifiers": {
        "cbn_institution_id": "24",
        "nibss_code": "000015"
      }
    }
  ]
}
```

`total` counts every match; `banks` holds the requested page. Banks are sorted by name.

A bank transfer dropdown for Nigeria needs only the banks with a NIBSS code:

```bash
curl "http://localhost:5006/api/countries/NG/banks?has=nibss_code"
```

To turn a code from a transfer back into a bank:

```bash
curl "http://localhost:5006/api/countries/NG/banks?nibss_code=090267"
```

### Get a bank

```http
GET /api/countries/{country_code}/banks/{bank_id}
```

```bash
curl http://localhost:5006/api/countries/NG/banks/access-bank
```

## Bank fields

| Field | Description |
| --- | --- |
| `id` | Slug made from the bank's name when it was first listed, for example `access-bank`. It stays the same when the bank is renamed, so it is safe to store. |
| `name` | The name exactly as the official register publishes it, including its capitalization. Only stray spaces and line breaks are removed. |
| `type` | One of the country's bank type codes, listed by `GET /api/countries/{country_code}`. |
| `identifiers` | Codes for the bank under the schemes the country declares, listed by `GET /api/countries/{country_code}`. A scheme is left out when the bank has no code under it. |

Nigeria's identifier schemes:

| Scheme | Description |
| --- | --- |
| `cbn_institution_id` | The bank's record ID in the CBN register. Mobile money operators come from a different CBN page and have none. |
| `nibss_code` | The 6-digit code NIBSS uses for the institution in NIBSS Instant Payment (NIP) transfers, for example `000014` for Access Bank and `100004` for OPay. Payment providers' transfer APIs either take this code or list it next to their own, so it can be matched to any provider. Banks that are not on NIP, which includes most small microfinance banks, have none. |

## Refreshing data

Rebuild one country's file from its source, then review and commit the diff:

```bash
python -m src.refresh NGA
git diff data/countries/NGA.json
```

The command prints which banks were added, removed or changed. Existing banks keep their ids. If the source fails or the new data does not pass validation, the file is left untouched.

### Nigeria's NIBSS codes

NIBSS does not publish its institution list openly; it serves it to connected institutions, and payment providers relay it to their API customers. To refresh the codes, copy `.env.example` to `.env` and set the URL of an API that returns the list, with its key. `.env` is ignored by git, so the endpoints and keys never reach the repository.

A relayed copy can leave institutions out, so up to five can be combined: the same setting names ending in `_2` to `_5` configure more endpoints, and the lists are merged by code.

```bash
cp .env.example .env
python -m src.refresh NGA
```

Without these settings, the refresh keeps the codes already in the file and updates everything else.

With them, the command also prints the review report: banks still without a code, and NIP institutions that matched no bank. Add `--verbose` to also list every match with the institution's name in the NIP list, to confirm each code belongs to its bank. A bank gets a code automatically only when its name matches exactly one NIP institution of the same type. When the two lists spell a name differently, add the bank's name exactly as the CBN publishes it, with its code, to `src/countries/nigeria/nibss_code_matches.json`, check that the code really belongs to that bank, and run the refresh again. A name mapped to `null` stays without a code.

The scheduled check compares the codes too when the repository has the same settings as secrets: `NIP_INSTITUTIONS_URL` and `NIP_INSTITUTIONS_API_KEY` (and `NIP_INSTITUTIONS_KEY_HEADER` if the header is not `X-API-Key`), plus the `_2` versions for a second list.

To check every country without writing anything, as the scheduled workflow does:

```bash
python -m src.refresh all --check
```

## Adding a country

1. Find an official, public source for the country's licensed banks, usually the central bank or banking regulator. Do not use sources whose terms forbid redistribution, such as the SWIFT BIC directory or paid sort-code directories.
2. Create `src/countries/<country>/profile.py` with a `CountryProfile`: ISO codes, name, currency, the bank types the regulator licenses, the identifier schemes the source provides, and a pattern for each scheme's values. Banks keep their ids between refreshes through any shared identifier, or failing that their exact name.
3. Create `src/countries/<country>/refresh.py` with a `fetch_dataset(client, previous_banks)` function that returns `{"sources": [...], "banks": [...]}`, where each bank has `name`, `type` and `identifiers`. `previous_banks` holds the banks already in the file, for values a source cannot supply on a given run. Use `SourceClient` for requests and `clean_text` for names.
4. Register the profile in `src/countries/registry.py`.
5. Run `python -m src.refresh <CODE>` to generate the data file.
6. Add tests for the refresh module using saved samples of the source's real responses in `tests/fixtures/<country>/`, then run the checks below.

## Development checks

```bash
ruff format --check .
ruff check .
mypy
pytest
```

## Notes on Nigeria's data

- The banks come from the JSON endpoints behind the CBN's Financial Institutions pages: one per licence category.
- Mobile money operators come from the CBN's Payment Service Providers page, which lists 17. The register's own mobile money list is shorter and leaves out OPay. Each operator's NIBSS code is the one its wallets use on NIP.
- The CBN register lists a few microfinance banks twice under different record IDs, with the same name, town and licence date. Each name is kept once, with its lowest record ID.
- The register also has a per-bank detail endpoint with licence tier and website, but it fails for many banks and its websites are out of date, so it is not used.

## Disclaimer

The data is compiled from public registers and may lag behind them. It is not affiliated with or endorsed by any regulator. Check the regulator's own list before relying on a bank's licence status.

## License

MIT. See [LICENSE](LICENSE).
