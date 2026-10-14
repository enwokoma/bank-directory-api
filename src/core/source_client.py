"""HTTP client for reading official bank registers during a data refresh.

Regulator websites are often slow, rate-limited or fronted by bot protection
that occasionally answers with an HTML page instead of JSON. This client spaces
requests out, retries transient failures, and raises one error type that the
refresh command can report cleanly. The API server never imports it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import requests

from src import __version__

USER_AGENT = f"bank-directory-api/{__version__} (bank list refresh)"
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class SourceError(Exception):
    """Raised when a source keeps failing after every retry."""


class _TransientResponse(Exception):
    pass


class SourceClient:
    """Fetch JSON politely: one request at a time with a minimum gap between them."""

    def __init__(
        self,
        *,
        delay_seconds: float = 0.25,
        timeout_seconds: float = 30,
        attempts: int = 4,
        backoff_seconds: float = 2.0,
        session: requests.Session | None = None,
    ) -> None:
        self.delay_seconds = delay_seconds
        self.timeout_seconds = timeout_seconds
        self.attempts = attempts
        self.backoff_seconds = backoff_seconds
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self._last_request_at = 0.0

    def get_json(self, url: str, params: dict[str, str] | None = None, headers: dict[str, str] | None = None) -> Any:
        """Return the decoded JSON body of a GET request, retrying transient failures."""
        # An HTML challenge page instead of JSON makes response.json() raise a ValueError, which is retried.
        return self._get(url, params, headers, lambda response: response.json())

    def get_text(self, url: str, params: dict[str, str] | None = None, headers: dict[str, str] | None = None) -> str:
        """Return the body of a GET request as text, such as an HTML page, retrying transient failures."""
        return self._get(url, params, headers, lambda response: response.text)

    def _get(
        self,
        url: str,
        params: dict[str, str] | None,
        headers: dict[str, str] | None,
        read: Callable[[requests.Response], Any],
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, self.attempts + 1):
            self._wait_turn()
            try:
                response = self.session.get(url, params=params, headers=headers, timeout=self.timeout_seconds)
                if response.status_code in _RETRY_STATUSES:
                    raise _TransientResponse(f"HTTP {response.status_code}")
                response.raise_for_status()
                return read(response)
            except requests.HTTPError as exc:
                raise SourceError(f"{url} answered {exc.response.status_code}") from exc
            except (requests.ConnectionError, requests.Timeout, _TransientResponse, ValueError) as exc:
                last_error = exc
                if attempt < self.attempts:
                    time.sleep(self.backoff_seconds * attempt)
        raise SourceError(f"{url} failed after {self.attempts} attempts: {last_error}") from last_error

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> SourceClient:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def _wait_turn(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.delay_seconds:
            time.sleep(self.delay_seconds - elapsed)
        self._last_request_at = time.monotonic()
