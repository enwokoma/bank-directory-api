"""Tests for detecting the bank an account number belongs to, from the number alone."""

import dataclasses
import json

import pytest

from app import app, create_app
from src.core.dataset import load_datasets
from src.core.detection import Candidate, recommended_count
from src.countries.nigeria import detection, nuban
from src.countries.nigeria.detection import DetectionSettings, InstitutionSettings, detect, load_settings
from src.countries.nigeria.profile import NIGERIA_PROFILE

DATASET = load_datasets()["NGA"]


def ids(result, count=None):
    return [candidate.bank["id"] for candidate in result.candidates[:count]]


def candidate(result, bank_id):
    return next(candidate for candidate in result.candidates if candidate.bank["id"] == bank_id)


def number_for(bank_id, serial="001656322"):
    """An account number whose check digit is right for this bank."""
    return nuban.make_account_number(detection.institution_code(DATASET.banks_by_id[bank_id]), serial)


class TestCheckDigit:
    def test_rules_out_institutions_whose_code_gives_another_digit(self):
        result = detect(DATASET, "5050114930")
        found = set(ids(result))
        assert {"providus-bank", "standard-chartered-bank-nigeria", "wema-bank", "zenith-bank"} <= found
        assert not {"guaranty-trust-bank", "access-bank", "united-bank-for-africa"} & found
        providus = candidate(result, "providus-bank")
        assert providus.institution_code == "000101"
        assert providus.check_digit_valid is True
        assert providus.reasons == ("check_digit",)

    def test_banks_are_tested_with_their_cbn_bank_code_not_their_nibss_code(self):
        gtbank = DATASET.banks_by_id["guaranty-trust-bank"]
        with_cbn_code = nuban.make_account_number("000058", "012345678")
        with_nibss_code = nuban.make_account_number(gtbank["identifiers"]["nibss_code"], "012345678")
        assert "guaranty-trust-bank" in ids(detect(DATASET, with_cbn_code))
        assert "guaranty-trust-bank" not in ids(detect(DATASET, with_nibss_code))

    def test_institutions_without_a_cbn_bank_code_are_tested_with_their_nibss_code(self):
        number = number_for("quest-merchant-bank")
        quest = candidate(detect(DATASET, number), "quest-merchant-bank")
        assert quest.institution_code == DATASET.banks_by_id["quest-merchant-bank"]["identifiers"]["nibss_code"]
        assert quest.check_digit_valid is True

    def test_only_active_institutions_on_nip_are_candidates(self):
        result = detect(DATASET, "0123456789")
        assert all(candidate.bank["status"] == "active" for candidate in result.candidates)
        assert all("nibss_code" in candidate.bank["identifiers"] for candidate in result.candidates)

    def test_the_number_leaves_a_tenth_of_the_institutions_plus_the_wallets(self):
        on_nip = sum(1 for bank in DATASET.banks if bank["status"] == "active" and "nibss_code" in bank["identifiers"])
        for number in ("0123456789", "2256475832", "5050114930"):
            count = len(detect(DATASET, number).candidates)
            assert on_nip / 20 < count < on_nip / 4, (number, count)

    def test_confidences_add_up_to_one_and_fall_from_first_to_last(self):
        result = detect(DATASET, "0123456789")
        confidences = [candidate.confidence for candidate in result.candidates]
        assert abs(sum(confidences) - 1) < 0.01
        assert confidences == sorted(confidences, reverse=True)
        assert all(0 < confidence <= 1 for confidence in confidences)

    def test_a_number_made_for_a_big_bank_puts_it_first(self):
        result = detect(DATASET, number_for("guaranty-trust-bank", "012345678"))
        assert ids(result, 1) == ["guaranty-trust-bank"]
        first = result.candidates[0]
        assert first.confidence > 0.5
        assert first.reasons == ("check_digit", "account_prefix")

    def test_types_narrow_the_candidates(self):
        result = detect(DATASET, "0123456789", types={"mobile_money", "payment_service"})
        assert result.candidates
        assert {candidate.bank["type"] for candidate in result.candidates} <= {"mobile_money", "payment_service"}


class TestPhoneNumbers:
    def test_a_mobile_number_points_to_the_wallets_first(self):
        result = detect(DATASET, "8012345678")
        assert result.looks_like_phone_number is True
        assert ids(result, 3) == ["opay-digital-services", "palmpay", "moniepoint-mfb"]
        assert "phone_number_account" in candidate(result, "opay-digital-services").reasons
        assert "phone_number_account" in candidate(result, "momo-payment-service-bank").reasons

    @pytest.mark.parametrize("value", ["0801 234 5678", "+234 801 234 5678", "08012345678"])
    def test_a_mobile_number_written_in_full_is_the_wallet_account_number(self, value):
        result = detect(DATASET, value)
        assert result.account_number == "8012345678"
        assert result.looks_like_phone_number is True

    def test_wallets_stay_in_the_list_for_other_numbers_but_low(self):
        """A wallet whose fallback code fails the check is kept: not all of its account numbers follow NUBAN."""
        numbers = (number_for("guaranty-trust-bank", f"{serial:09d}") for serial in range(1, 100))
        number = next(number for number in numbers if not nuban.is_valid(number, "100004"))
        result = detect(DATASET, number)
        assert result.looks_like_phone_number is False
        opay = candidate(result, "opay-digital-services")
        assert opay.check_digit_valid is False
        assert opay.reasons == ()
        assert opay.confidence < 0.05

    def test_a_number_a_bank_could_have_issued_outranks_the_wallets(self):
        result = detect(DATASET, number_for("first-bank-nigeria", "312345678"))
        assert ids(result, 1) == ["first-bank-nigeria"]
        assert candidate(result, "opay-digital-services").confidence < 0.1

    def test_banks_whose_codes_share_a_weighted_sum_are_told_apart_by_leading_digits(self):
        """Access Bank (044), UBA (033) and First Bank (011) always pass or fail together: 40, 30 and 10 are multiples of 10."""
        number = number_for("united-bank-for-africa", "212345678")
        result = detect(DATASET, number)
        assert all(candidate(result, bank_id).check_digit_valid for bank_id in ("access-bank", "united-bank-for-africa"))
        assert candidate(result, "first-bank-nigeria").check_digit_valid
        # A 2 is a known start for UBA and First Bank, not for Access Bank.
        assert set(ids(result, 2)) == {"united-bank-for-africa", "first-bank-nigeria"}
        assert "account_prefix" not in candidate(result, "access-bank").reasons


class TestHints:
    def test_a_hint_naming_the_bank_puts_it_first(self):
        result = detect(DATASET, "0123456789", hint="GTBank 0123456789 John Doe")
        assert ids(result, 1) == ["guaranty-trust-bank"]
        assert result.candidates[0].reasons[0] == "hint"
        assert result.candidates[0].confidence > 0.8

    def test_a_hint_keeps_an_institution_the_check_digit_rules_out(self):
        number = number_for("guaranty-trust-bank")
        assert "access-bank" not in ids(detect(DATASET, number))
        result = detect(DATASET, number, hint="Access Bank")
        access = candidate(result, "access-bank")
        assert access.check_digit_valid is False
        assert access.reasons == ("hint",)
        assert ids(result, 1) == ["access-bank"]

    @pytest.mark.parametrize("hint", ["opay", "OPAY", "Send to O-Pay please", "Opay Digital Services"])
    def test_hints_match_aliases_and_names_whatever_the_spelling(self, hint):
        assert ids(detect(DATASET, "0123456789", hint=hint), 1) == ["opay-digital-services"]

    def test_hints_match_whole_words_only(self):
        result = detect(DATASET, number_for("united-bank-for-africa"), hint="cuba")
        assert "hint" not in candidate(result, "united-bank-for-africa").reasons

    def test_hints_match_trading_and_register_names(self):
        assert ids(detect(DATASET, "0123456789", hint="Nombank"), 1) == ["amucha-microfinance-bank"]
        assert ids(detect(DATASET, "0123456789", hint="Guaranty Trust Bank Plc"), 1) == ["guaranty-trust-bank"]

    def test_an_empty_hint_changes_nothing(self):
        assert ids(detect(DATASET, "0123456789", hint="   ")) == ids(detect(DATASET, "0123456789"))

    def test_institutions_a_hint_leaves_with_no_confidence_are_left_out(self):
        result = detect(DATASET, "8012345678", hint="opay")
        assert all(candidate.confidence > 0 for candidate in result.candidates)
        assert len(result.candidates) < 5
        assert ids(result, 1) == ["opay-digital-services"]


def fake_candidates(*confidences):
    return [
        Candidate(
            bank={"id": f"bank-{index}"}, confidence=confidence, reasons=(), institution_code="000000", check_digit_valid=True
        )
        for index, confidence in enumerate(confidences, start=1)
    ]


class TestRecommendedCount:
    def test_takes_the_fewest_candidates_that_reach_the_coverage(self):
        assert recommended_count(fake_candidates(0.6, 0.25, 0.1, 0.03, 0.02), 0.9) == 3
        assert recommended_count(fake_candidates(0.6, 0.25, 0.1, 0.03, 0.02), 0.5) == 1
        assert recommended_count(fake_candidates(0.6, 0.25, 0.1, 0.03, 0.02), 0.85) == 2

    def test_caps_an_ambiguous_number_at_the_limit(self):
        assert recommended_count(fake_candidates(*[0.1] * 20), 0.9) == 5
        assert recommended_count(fake_candidates(*[0.1] * 20), 0.9, limit=2) == 2

    def test_always_recommends_one_when_there_are_any(self):
        assert recommended_count(fake_candidates(0.2, 0.2), 0.99) == 2
        assert recommended_count(fake_candidates(0.2), 0.99) == 1
        assert recommended_count([], 0.9) == 0


class TestSettings:
    def test_committed_settings_name_active_institutions_on_nip(self):
        settings = load_settings()
        for bank_id in settings.institutions:
            bank = DATASET.banks_by_id[bank_id]
            assert bank["status"] == "active", bank_id
            assert "nibss_code" in bank["identifiers"], bank_id

    def test_committed_settings_cover_every_bank_type(self):
        assert set(load_settings().default_shares) == set(NIGERIA_PROFILE.bank_type_codes())

    def test_aliases_name_one_institution_each(self):
        seen = {}
        for bank_id, institution in load_settings().institutions.items():
            for alias in institution.aliases:
                assert alias not in seen, f"{alias!r} is an alias of both {seen.get(alias)} and {bank_id}"
                seen[alias] = bank_id

    @pytest.mark.parametrize(
        "content, problem",
        [
            ({"institutions": {}}, "default_share_by_type"),
            ({"default_share_by_type": {"commercial": 1}, "institutions": {}}, "no default share for bank types"),
            ({"default_share_by_type": {"commercial": 0}, "institutions": {}}, "positive number"),
            ({"default_share_by_type": {"commercial": 1}, "institutions": {"x": {"share": -1}}}, "positive number"),
            ({"default_share_by_type": {"commercial": 1}, "institutions": {"x": {"phone_number_accounts": 2}}}, "fraction"),
            ({"default_share_by_type": {"commercial": 1}, "institutions": {"x": {"prefixes": ["0"]}}}, "unknown keys"),
            ({"default_share_by_type": {"commercial": 1}, "institutions": {"x": {"account_prefixes": ["a"]}}}, "digits"),
            ({"default_share_by_type": {"commercial": 1}, "institutions": {"x": {"aliases": [" "]}}}, "non-empty"),
            ({"default_share_by_type": {"commercial": 1}, "institutions": {"x": "opay"}}, "must be an object"),
            ({"default_share_by_type": {"commercial": 1}, "institutions": {"x": {"other_bank_codes": ["6020"]}}}, "3, 5 or 6"),
        ],
    )
    def test_rejects_malformed_settings(self, tmp_path, content, problem):
        path = tmp_path / "account_detection.json"
        path.write_text(json.dumps(content), encoding="utf-8")
        with pytest.raises(ValueError, match=problem):
            load_settings(path)

    def test_unlisted_institutions_share_their_type_default(self):
        settings = DetectionSettings(default_shares=dict.fromkeys(NIGERIA_PROFILE.bank_type_codes(), 1.0), institutions={})
        result = detect(DATASET, "0123456789", settings=settings)
        assert len({candidate.confidence for candidate in result.candidates}) == 1
        assert all(candidate.reasons == ("check_digit",) for candidate in result.candidates)

    def test_other_bank_codes_are_tested_too(self):
        """Accion issued account numbers under its old 3-digit NIBSS code 602 before the CBN's 50009."""
        settings = DetectionSettings(
            default_shares=dict.fromkeys(NIGERIA_PROFILE.bank_type_codes(), 1.0),
            institutions={"accion-microfinance-bank": InstitutionSettings(other_bank_codes=("602",))},
        )
        old = nuban.make_account_number("000602", "001234567")
        accion = candidate(detect(DATASET, old, settings=settings), "accion-microfinance-bank")
        assert accion.check_digit_valid is True
        assert accion.institution_code == "000602"
        new = nuban.make_account_number("950009", "001234567")
        assert candidate(detect(DATASET, new, settings=settings), "accion-microfinance-bank").institution_code == "950009"

    def test_committed_other_bank_codes_cover_the_early_nip_microfinance_banks(self):
        settings = load_settings()
        assert settings.institutions["accion-microfinance-bank"].other_bank_codes == ("602",)
        assert settings.institutions["fut-minna"].other_bank_codes == ("832",)

    def test_a_listed_share_outweighs_the_default(self):
        settings = DetectionSettings(
            default_shares=dict.fromkeys(NIGERIA_PROFILE.bank_type_codes(), 1.0),
            institutions={"providus-bank": InstitutionSettings(share=100)},
        )
        assert ids(detect(DATASET, "5050114930", settings=settings), 1) == ["providus-bank"]


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


class TestApi:
    def test_detects_from_a_query_parameter(self, client):
        response = client.get("/api/detect-bank?account_number=8012345678")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["country"] == {"alpha2": "NG", "alpha3": "NGA", "name": "Nigeria"}
        assert data["account_number"] == "8012345678"
        assert data["looks_like_phone_number"] is True
        assert data["best_guess"] == data["candidates"][0]
        assert data["best_guess"]["bank"]["id"] == "opay-digital-services"
        assert list(data["best_guess"]) == ["confidence", "reasons", "institution_code", "check_digit_valid", "bank"]
        assert data["limit"] == 10
        assert len(data["candidates"]) == 10
        assert data["total_candidates"] > 10

    def test_detects_from_a_json_body(self, client):
        response = client.post("/api/detect-bank", json={"account_number": "0123456789", "hint": "GTBank", "limit": 2})
        assert response.status_code == 200
        data = response.get_json()
        assert [candidate["bank"]["id"] for candidate in data["candidates"]][0] == "guaranty-trust-bank"
        assert data["candidates"][0]["reasons"][0] == "hint"
        # A hint is decisive, so every other candidate's confidence rounds to 0 and is left out.
        assert data["limit"] == 2
        assert [candidate["bank"]["id"] for candidate in data["candidates"]] == ["guaranty-trust-bank"]

    def test_detects_from_a_form_body(self, client):
        response = client.post("/api/detect-bank", data={"account_number": "0801 234 5678"})
        assert response.status_code == 200
        assert response.get_json()["account_number"] == "8012345678"

    @pytest.mark.parametrize("path", ["/api/countries/NG/detect-bank", "/api/countries/nga/detect-bank"])
    def test_detects_under_the_country(self, client, path):
        assert client.get(f"{path}?account_number=0123456789").status_code == 200
        assert client.post(path, json={"account_number": "0123456789"}).status_code == 200

    def test_accepts_a_country_parameter(self, client):
        assert client.get("/api/detect-bank?country=NG&account_number=0123456789").status_code == 200
        assert client.get("/api/detect-bank?country=XX&account_number=0123456789").status_code == 404
        assert client.get("/api/countries/XX/detect-bank?account_number=0123456789").status_code == 404

    def test_recommends_the_top_candidates_up_to_the_coverage(self, client):
        data = client.get("/api/detect-bank?account_number=0016563228").get_json()
        recommended = data["recommended"]
        assert list(recommended) == ["coverage", "confidence", "candidates"]
        assert recommended["coverage"] == 0.9
        assert recommended["candidates"] == data["candidates"][: len(recommended["candidates"])]
        ids = [candidate["bank"]["id"] for candidate in recommended["candidates"]]
        assert ids[0] == "guaranty-trust-bank"
        assert 1 <= len(ids) <= 5
        confidences = [candidate["confidence"] for candidate in recommended["candidates"]]
        assert recommended["confidence"] == round(sum(confidences), 4)
        # The shortest prefix that reaches the coverage: with the last one it does, without it does not.
        assert recommended["confidence"] >= 0.9
        assert sum(confidences[:-1]) < 0.9

    def test_coverage_widens_or_narrows_the_recommendation(self, client):
        narrow = client.get("/api/detect-bank?account_number=0016563228&coverage=0.5").get_json()["recommended"]
        wide = client.post("/api/detect-bank", json={"account_number": "0016563228", "coverage": 0.99}).get_json()[
            "recommended"
        ]
        assert len(narrow["candidates"]) == 1
        assert len(wide["candidates"]) > len(narrow["candidates"])
        assert wide["coverage"] == 0.99

    def test_recommendation_never_exceeds_five_or_the_limit(self, client):
        ambiguous = client.get("/api/detect-bank?account_number=5050114930&coverage=0.99").get_json()["recommended"]
        assert len(ambiguous["candidates"]) == 5
        assert ambiguous["confidence"] < 0.99
        capped = client.get("/api/detect-bank?account_number=5050114930&limit=2").get_json()
        assert len(capped["recommended"]["candidates"]) <= 2

    @pytest.mark.parametrize("coverage", ["0.3", "1", "abc", "nan"])
    def test_rejects_bad_coverage(self, client, coverage):
        response = client.get(f"/api/detect-bank?account_number=0016563228&coverage={coverage}")
        assert response.status_code == 400
        assert "coverage must be" in response.get_json()["message"]

    def test_type_and_limit_narrow_the_answer(self, client):
        data = client.get("/api/detect-bank?account_number=0123456789&type=mobile_money&limit=3").get_json()
        assert len(data["candidates"]) == 3
        assert {candidate["bank"]["type"] for candidate in data["candidates"]} == {"mobile_money"}
        assert data["total_candidates"] >= 3

    @pytest.mark.parametrize(
        "query, message",
        [
            ("", "account_number is required."),
            ("account_number=", "account_number is required."),
            ("account_number=12345", "account_number must be 10 digits, not 5"),
            ("account_number=012345678a", "only digits"),
            ("account_number=0123456789&limit=0", "limit must be between 1 and 100."),
            ("account_number=0123456789&limit=101", "limit must be between 1 and 100."),
            ("account_number=0123456789&type=savings", "Unknown bank type savings"),
            ("account_number=0123456789&hint=" + "x" * 201, "hint must be at most 200 characters."),
        ],
    )
    def test_rejects_bad_input(self, client, query, message):
        response = client.get(f"/api/detect-bank?{query}")
        assert response.status_code == 400
        assert message in response.get_json()["message"]

    def test_a_json_number_loses_its_leading_zeros_so_is_refused(self, client):
        response = client.post("/api/detect-bank", json={"account_number": 123456789})
        assert response.status_code == 400
        assert "as a string" in response.get_json()["message"]

    def test_a_json_body_that_is_not_an_object_is_refused(self, client):
        response = client.post("/api/detect-bank", data="[1, 2]", content_type="application/json")
        assert response.status_code == 400
        assert "JSON object" in response.get_json()["message"]
        assert client.post("/api/detect-bank", json={"account_number": ["0123456789"]}).status_code == 400

    def test_get_answers_are_cacheable_and_post_answers_are_not(self, client):
        cached = client.get("/api/detect-bank?account_number=0123456789")
        assert cached.headers["Cache-Control"] == "public, max-age=3600"
        assert "ETag" in cached.headers
        posted = client.post("/api/detect-bank", json={"account_number": "0123456789"})
        assert "Cache-Control" not in posted.headers

    def test_the_country_says_it_has_bank_detection(self, client):
        assert client.get("/api/countries/NG").get_json()["country"]["bank_detection"] is True

    def test_swagger_lists_both_routes_with_both_methods(self, client):
        spec = client.get("/apispec_1.json").get_json()
        for path in ("/api/detect-bank", "/api/countries/{country_code}/detect-bank"):
            assert set(spec["paths"][path]) == {"get", "post"}
            query = {parameter["name"] for parameter in spec["paths"][path]["get"]["parameters"]}
            assert {"account_number", "hint", "type", "limit"} <= query
            body = next(parameter for parameter in spec["paths"][path]["post"]["parameters"] if parameter["in"] == "body")
            assert body["schema"]["required"] == ["account_number"]
        assert "country" in {parameter["name"] for parameter in spec["paths"]["/api/detect-bank"]["get"]["parameters"]}


class TestWithoutDetection:
    """Against a dataset whose country has no detection scheme."""

    @pytest.fixture
    def client(self):
        dataset = load_datasets()["NGA"]
        profile = dataclasses.replace(dataset.profile, detection_module="")
        plain_app = create_app()
        plain_app.extensions["bank_datasets"] = {"NGA": dataclasses.replace(dataset, profile=profile)}
        return plain_app.test_client()

    def test_the_short_route_needs_a_country_it_can_detect_in(self, client):
        response = client.get("/api/detect-bank?account_number=0123456789")
        assert response.status_code == 400
        assert response.get_json()["message"] == "country is required. Countries with bank detection: none."

    def test_the_country_route_says_detection_is_not_available(self, client):
        response = client.get("/api/countries/NG/detect-bank?account_number=0123456789")
        assert response.status_code == 404
        assert response.get_json()["message"] == "Bank detection is not available for Nigeria yet."
        assert client.get("/api/countries/NG").get_json()["country"]["bank_detection"] is False
