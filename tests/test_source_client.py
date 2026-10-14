"""Tests for the HTTP client used to read official sources."""

import pytest
import requests

from src.core.source_client import SourceClient, SourceError


class FakeResponse:
    def __init__(self, status_code=200, body=None, text=""):
        self.status_code = status_code
        self._body = body
        self.text = text

    def json(self):
        if self._body is None:
            raise requests.JSONDecodeError("Expecting value", self.text, 0)
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"HTTP {self.status_code}")
            error.response = self
            raise error


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        return self.responses.pop(0)

    def close(self):
        pass


def make_client(*responses):
    session = FakeSession(responses)
    return SourceClient(delay_seconds=0, backoff_seconds=0, session=session), session


class TestSourceClient:
    def test_retries_server_errors_and_html_pages(self):
        client, session = make_client(FakeResponse(500), FakeResponse(200, text="<html>"), FakeResponse(200, body=[1]))
        assert client.get_json("https://example.test/") == [1]
        assert session.calls == 3

    def test_gives_up_after_every_attempt_fails(self):
        client, session = make_client(*[FakeResponse(503)] * 4)
        with pytest.raises(SourceError, match="after 4 attempts"):
            client.get_json("https://example.test/")
        assert session.calls == 4

    def test_does_not_retry_client_errors(self):
        client, session = make_client(FakeResponse(404))
        with pytest.raises(SourceError, match="answered 404"):
            client.get_json("https://example.test/")
        assert session.calls == 1

    def test_identifies_itself(self):
        client, session = make_client()
        assert session.headers["User-Agent"].startswith("bank-directory-api/")
