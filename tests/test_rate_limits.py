"""Tests for the hosted service's rate limits."""

import pytest

from app import create_app
from src.core.settings import Settings


def make_client(**overrides):
    settings = Settings(rate_limit_storage_uri="memory://", anonymous_rate_limit="3 per minute", **overrides)
    app = create_app(settings)
    app.config["TESTING"] = True
    return app.test_client()


def get(client, path="/api/countries", ip="203.0.113.1", **kwargs):
    return client.get(path, environ_base={"REMOTE_ADDR": ip}, **kwargs)


def test_limits_requests_without_a_key_per_ip():
    client = make_client()
    responses = [get(client) for _ in range(4)]
    assert [response.status_code for response in responses] == [200, 200, 200, 429]
    assert responses[0].headers["X-RateLimit-Limit"] == "3"
    assert responses[0].headers["X-RateLimit-Remaining"] == "2"
    assert "X-RateLimit-Reset" in responses[0].headers


def test_a_refused_request_gets_json_and_retry_after():
    client = make_client()
    for _ in range(3):
        get(client)
    refused = get(client)
    assert refused.status_code == 429
    assert refused.get_json() == {"success": False, "message": "Rate limit exceeded: 3 per 1 minute. Try again later."}
    assert int(refused.headers["Retry-After"]) > 0
    assert refused.headers["Access-Control-Allow-Origin"] == "*"
    assert "Cache-Control" not in refused.headers


def test_each_ip_has_its_own_allowance():
    client = make_client()
    for _ in range(3):
        get(client, ip="203.0.113.1")
    assert get(client, ip="203.0.113.1").status_code == 429
    assert get(client, ip="203.0.113.2").status_code == 200


def test_behind_a_proxy_the_forwarded_address_counts():
    client = make_client(trusted_proxies=1)
    for _ in range(3):
        get(client, headers={"X-Forwarded-For": "198.51.100.7"}, ip="10.0.0.2")
    assert get(client, headers={"X-Forwarded-For": "198.51.100.7"}, ip="10.0.0.2").status_code == 429
    assert get(client, headers={"X-Forwarded-For": "198.51.100.8"}, ip="10.0.0.2").status_code == 200


def test_without_trusted_proxies_a_forged_forwarded_address_is_ignored():
    client = make_client()
    for number in range(3):
        get(client, headers={"X-Forwarded-For": f"198.51.100.{number}"})
    assert get(client, headers={"X-Forwarded-For": "198.51.100.99"}).status_code == 429


@pytest.mark.parametrize("path", ["/", "/api-docs", "/apispec_1.json"])
def test_health_check_and_docs_are_not_limited(path):
    client = make_client()
    assert all(get(client, path).status_code == 200 for _ in range(5))


def test_browser_preflight_requests_are_not_counted():
    client = make_client()
    preflight = client.options("/api/countries", environ_base={"REMOTE_ADDR": "203.0.113.1"})
    for _ in range(3):
        client.options("/api/countries", environ_base={"REMOTE_ADDR": "203.0.113.1"})
    assert preflight.status_code == 200
    assert preflight.headers["Access-Control-Allow-Headers"] == "X-API-Key, Authorization, Content-Type"
    assert get(client).status_code == 200


def test_browsers_can_read_the_rate_limit_headers():
    response = get(make_client())
    assert "X-RateLimit-Remaining" in response.headers["Access-Control-Expose-Headers"]


def test_limits_are_off_unless_a_store_is_configured():
    app = create_app(Settings(anonymous_rate_limit="1 per minute"))
    client = app.test_client()
    assert all(get(client).status_code == 200 for _ in range(5))
    assert "X-RateLimit-Limit" not in get(client).headers
