"""API tests against the committed country data files."""

import pytest

from app import app


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
        assert list(data["banks"][0]) == ["id", "name", "type", "identifiers"]

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
