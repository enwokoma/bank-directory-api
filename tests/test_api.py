"""API tests against the committed country data files."""

import json

import pytest

from app import app, create_app
from src import __version__
from src.core.dataset import load_datasets
from src.core.settings import Settings


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def get_json(client, path, status=200):
    response = client.get(path)
    assert response.status_code == status, response.get_data(as_text=True)
    return response.get_json()


class TestServiceEndpoints:
    def test_health_check(self, client):
        assert get_json(client, "/")["status"] == "healthy"

    def test_swagger_ui_and_spec_are_served(self, client):
        assert client.get("/api-docs").status_code == 200
        spec = get_json(client, "/apispec_1.json")
        assert spec["info"]["version"] == __version__
        assert "/api/countries/{country_code}/banks" in spec["paths"]

    def test_unknown_route_returns_json(self, client):
        data = get_json(client, "/api/nothing-here", status=404)
        assert data["success"] is False

    def test_wrong_method_returns_json(self, client):
        response = client.post("/api/countries")
        assert response.status_code == 405
        assert response.get_json()["success"] is False


class TestCountries:
    def test_lists_nigeria(self, client):
        countries = get_json(client, "/api/countries")["countries"]
        nigeria = next(country for country in countries if country["alpha3"] == "NGA")
        assert nigeria["alpha2"] == "NG"
        assert nigeria["currency"] == "NGN"
        assert nigeria["bank_count"] > 0

    @pytest.mark.parametrize("code", ["NG", "ng", "NGA", "nga"])
    def test_accepts_alpha2_and_alpha3_in_any_case(self, client, code):
        assert get_json(client, f"/api/countries/{code}")["country"]["alpha3"] == "NGA"

    def test_country_detail_counts_every_bank_once(self, client):
        country = get_json(client, "/api/countries/NG")["country"]
        assert sum(bank_type["bank_count"] for bank_type in country["bank_types"]) == country["bank_count"]
        assert country["identifier_schemes"][0]["code"] == "cbn_institution_id"
        assert country["sources"][0]["url"].startswith("https://www.cbn.gov.ng/")

    def test_unknown_country_is_404(self, client):
        data = get_json(client, "/api/countries/XX", status=404)
        assert data == {
            "success": False,
            "message": "Unsupported country code: XX. GET /api/countries lists the supported countries.",
        }
        assert get_json(client, "/api/countries/XX/banks", status=404)["success"] is False
        assert get_json(client, "/api/countries/XX/banks/access-bank", status=404)["success"] is False


class TestBankList:
    def test_returns_every_bank_sorted_by_name(self, client):
        country = get_json(client, "/api/countries/NG")["country"]
        data = get_json(client, "/api/countries/NG/banks")
        assert data["country"] == {"alpha2": "NG", "alpha3": "NGA", "name": "Nigeria"}
        assert data["total"] == len(data["banks"]) == country["bank_count"]
        assert data["offset"] == 0
        assert data["limit"] is None
        assert list(data["banks"][0]) == ["id", "name", "type", "status", "identifiers"]
        assert {bank["status"] for bank in data["banks"]} == {"active"}

    def test_filters_by_one_or_more_types(self, client):
        counts = {item["code"]: item["bank_count"] for item in get_json(client, "/api/countries/NG")["country"]["bank_types"]}
        commercial = get_json(client, "/api/countries/NG/banks?type=commercial")
        assert commercial["total"] == counts["commercial"]
        assert {bank["type"] for bank in commercial["banks"]} == {"commercial"}

        both = get_json(client, "/api/countries/NG/banks?type=Commercial, merchant")
        assert both["total"] == counts["commercial"] + counts["merchant"]

    def test_rejects_unknown_type(self, client):
        message = get_json(client, "/api/countries/NG/banks?type=savings", status=400)["message"]
        assert "savings" in message
        assert "commercial" in message

    @pytest.mark.parametrize("query", ["zenith", "ZENITH", "  Zenith   bank ", "zenith-bank"])
    def test_searches_names_and_ids(self, client, query):
        banks = get_json(client, f"/api/countries/NG/banks?q={query}")["banks"]
        assert "zenith-bank" in [bank["id"] for bank in banks]

    def test_search_and_type_combine(self, client):
        banks = get_json(client, "/api/countries/NG/banks?q=bank&type=merchant")["banks"]
        assert banks
        assert all(bank["type"] == "merchant" for bank in banks)

    def test_finds_a_bank_by_identifier(self, client):
        data = get_json(client, "/api/countries/NG/banks?cbn_institution_id=1")
        assert [bank["id"] for bank in data["banks"]] == ["access-bank"]
        assert get_json(client, "/api/countries/NG/banks?cbn_institution_id=999999")["total"] == 0

    def test_lists_only_banks_that_have_an_identifier(self, client):
        banks = get_json(client, "/api/countries/NG/banks?has=cbn_institution_id")["banks"]
        assert banks
        assert all("cbn_institution_id" in bank["identifiers"] for bank in banks)

    def test_rejects_unknown_identifier_schemes(self, client):
        message = get_json(client, "/api/countries/NG/banks?has=swift", status=400)["message"]
        assert "swift" in message
        assert "nibss_code" in message

    def test_pages_with_limit_and_offset(self, client):
        everything = get_json(client, "/api/countries/NG/banks")["banks"]
        page = get_json(client, "/api/countries/NG/banks?limit=5&offset=5")
        assert page["banks"] == everything[5:10]
        assert page["total"] == len(everything)
        assert (page["limit"], page["offset"]) == (5, 5)

    @pytest.mark.parametrize(
        "query",
        ["limit=0", "limit=1001", "limit=ten", "offset=-1", "offset=1.5"],
    )
    def test_rejects_bad_paging(self, client, query):
        assert get_json(client, f"/api/countries/NG/banks?{query}", status=400)["success"] is False


class TestStatus:
    """Against a small dataset with one delisted bank, since the committed data may have none."""

    @pytest.fixture
    def client(self, tmp_path):
        def bank(bank_id, name, status, cbn_id):
            return {
                "id": bank_id,
                "name": name,
                "type": "commercial",
                "status": status,
                "identifiers": {"cbn_institution_id": cbn_id},
            }

        raw = {
            "country": "NGA",
            "retrieved_on": "2026-10-20",
            "sources": [{"name": "Central Bank of Nigeria", "url": "https://www.cbn.gov.ng/"}],
            "banks": [
                bank("access-bank", "Access Bank Plc", "active", "1"),
                bank("heritage-bank", "Heritage Bank Plc", "delisted", "9"),
            ],
        }
        (tmp_path / "NGA.json").write_text(json.dumps(raw), encoding="utf-8")
        status_app = create_app()
        status_app.extensions["bank_datasets"] = load_datasets(tmp_path)
        return status_app.test_client()

    def ids(self, client, query=""):
        return [bank["id"] for bank in get_json(client, f"/api/countries/NG/banks{query}")["banks"]]

    def test_lists_only_active_banks_by_default(self, client):
        assert self.ids(client) == ["access-bank"]
        assert self.ids(client, "?status=active") == ["access-bank"]

    def test_lists_delisted_banks_on_request(self, client):
        assert self.ids(client, "?status=delisted") == ["heritage-bank"]
        assert self.ids(client, "?status=All") == ["access-bank", "heritage-bank"]

    def test_identifier_filters_default_to_active_banks_too(self, client):
        assert self.ids(client, "?cbn_institution_id=9") == []
        assert self.ids(client, "?cbn_institution_id=9&status=all") == ["heritage-bank"]

    def test_rejects_unknown_status(self, client):
        message = get_json(client, "/api/countries/NG/banks?status=closed", status=400)["message"]
        assert message == "Unknown status closed. Use one of: active, delisted, all."

    def test_a_delisted_bank_is_still_found_by_id(self, client):
        assert get_json(client, "/api/countries/NG/banks/heritage-bank")["bank"]["status"] == "delisted"

    def test_country_counts_cover_active_banks(self, client):
        country = get_json(client, "/api/countries/NG")["country"]
        assert (country["bank_count"], country["delisted_bank_count"]) == (1, 1)
        assert next(item for item in country["bank_types"] if item["code"] == "commercial")["bank_count"] == 1


class TestBankDetail:
    def test_returns_one_bank(self, client):
        data = get_json(client, "/api/countries/NGA/banks/access-bank")
        assert data["bank"]["name"] == "Access Bank Plc"
        assert data["bank"]["type"] == "commercial"
        assert data["country"]["alpha2"] == "NG"

    def test_ids_ignore_case(self, client):
        assert get_json(client, "/api/countries/NG/banks/ACCESS-BANK")["bank"]["id"] == "access-bank"

    def test_unknown_bank_is_404(self, client):
        assert get_json(client, "/api/countries/NG/banks/no-such-bank", status=404)["success"] is False


class TestCachingAndCors:
    def test_api_responses_can_be_cached_and_revalidated(self, client):
        first = client.get("/api/countries/NG/banks?type=merchant")
        assert first.headers["Cache-Control"] == "public, max-age=3600"
        assert first.headers["Access-Control-Allow-Origin"] == "*"
        etag = first.headers["ETag"]

        again = client.get("/api/countries/NG/banks?type=merchant", headers={"If-None-Match": etag})
        assert again.status_code == 304
        assert again.get_data() == b""

    def test_errors_are_not_cached(self, client):
        response = client.get("/api/countries/XX")
        assert "Cache-Control" not in response.headers
        assert "ETag" not in response.headers


class TestSecurityHeaders:
    @pytest.mark.parametrize("path", ["/", "/api/countries", "/api/countries/XX"])
    def test_every_response_forbids_content_type_guessing(self, client, path):
        assert client.get(path).headers["X-Content-Type-Options"] == "nosniff"

    def test_https_responses_keep_browsers_on_https(self, client):
        response = client.get("/api/countries", base_url="https://localhost")
        assert response.headers["Strict-Transport-Security"] == "max-age=31536000"

    def test_plain_http_responses_do_not_send_hsts(self, client):
        assert "Strict-Transport-Security" not in client.get("/api/countries").headers

    def test_behind_a_trusted_proxy_https_comes_from_the_forwarded_protocol(self):
        proxied = create_app(Settings(trusted_proxies=1)).test_client()
        response = proxied.get("/api/countries", headers={"X-Forwarded-Proto": "https"})
        assert response.headers["Strict-Transport-Security"] == "max-age=31536000"

    def test_without_trusted_proxies_a_forged_protocol_is_ignored(self, client):
        response = client.get("/api/countries", headers={"X-Forwarded-Proto": "https"})
        assert "Strict-Transport-Security" not in response.headers
