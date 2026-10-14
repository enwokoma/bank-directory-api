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
        assert "/api/countries/{country_code}" in spec["paths"]


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
