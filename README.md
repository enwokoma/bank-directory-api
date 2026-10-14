# Bank Directory API

A Flask API that lists the licensed banks of each country, compiled from that country's official register. Countries are added one release at a time; each one comes with a script that rebuilds its data from the regulator's own list.

## Coverage

| Country | Codes | Banks | Bank types | Source |
| --- | --- | --- | --- | --- |
| Nigeria | `NG` / `NGA` | 863 | commercial, merchant, non-interest, payment service, microfinance, primary mortgage | [Central Bank of Nigeria: Financial Institutions](https://www.cbn.gov.ng/supervision/finstitutions.html) |

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
        refresh.py        Reads the CBN register
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
      "bank_count": 863,
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
        "cbn_institution_id": "24"
      }
    }
  ]
}
```

`total` counts every match; `banks` holds the requested page. Banks are sorted by name.

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
| `identifiers` | Codes for the bank under the schemes the country declares. For Nigeria this is `cbn_institution_id`, the bank's record ID in the CBN register. |

## Refreshing data

Rebuild one country's file from its source, then review and commit the diff:

```bash
python -m src.refresh NGA
git diff data/countries/NGA.json
```

The command prints which banks were added, removed or changed. Existing banks keep their ids. If the source fails or the new data does not pass validation, the file is left untouched.

To check every country without writing anything, as the scheduled workflow does:

```bash
python -m src.refresh all --check
```

## Adding a country

1. Find an official, public source for the country's licensed banks, usually the central bank or banking regulator. Do not use sources whose terms forbid redistribution, such as the SWIFT BIC directory or paid sort-code directories.
2. Create `src/countries/<country>/profile.py` with a `CountryProfile`: ISO codes, name, currency, the bank types the regulator licenses, and the identifier schemes the source provides. The first identifier scheme is used to keep ids stable between refreshes, so it must be one every bank has.
3. Create `src/countries/<country>/refresh.py` with a `fetch_dataset(client)` function that returns `{"sources": [...], "banks": [...]}`, where each bank has `name`, `type` and `identifiers`. Use `SourceClient` for requests and `clean_text` for names.
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

- The list comes from the JSON endpoints behind the CBN's Financial Institutions pages: one per licence category.
- The CBN register lists a few microfinance banks twice under different record IDs, with the same name, town and licence date. Each name is kept once, with its lowest record ID.
- The register also has a per-bank detail endpoint with licence tier and website, but it fails for many banks and its websites are out of date, so it is not used.

## Disclaimer

The data is compiled from public registers and may lag behind them. It is not affiliated with or endorsed by any regulator. Check the regulator's own list before relying on a bank's licence status.

## License

MIT. See [LICENSE](LICENSE).
