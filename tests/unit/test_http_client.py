# ABOUTME: Unit tests for the HTTP client abstraction.
# ABOUTME: Tests the HttpClient protocol, BookeryHttpClient, rate limiting, and error handling.

import time

import httpx
import pytest

from bookery.metadata.http import (
    BookeryHttpClient,
    HttpClient,
    MetadataFetchError,
)


class FakeTransport(httpx.BaseTransport):
    """Fake transport for httpx that returns canned responses."""

    def __init__(self, responses: list[httpx.Response] | None = None) -> None:
        self._responses = list(responses or [])
        self._call_count = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self._call_count += 1
        if self._responses:
            return self._responses.pop(0)
        return httpx.Response(200, json={"ok": True})

    @property
    def call_count(self) -> int:
        return self._call_count


class TestHttpClientProtocol:
    """Tests for HttpClient protocol compliance."""

    def test_bookery_client_satisfies_protocol(self) -> None:
        """BookeryHttpClient satisfies the HttpClient protocol."""
        client = BookeryHttpClient(min_request_interval=0.0)
        assert isinstance(client, HttpClient)


class TestBookeryHttpClient:
    """Tests for BookeryHttpClient concrete class."""

    def test_get_returns_json(self) -> None:
        """GET request returns parsed JSON response."""
        transport = FakeTransport()
        client = BookeryHttpClient(min_request_interval=0.0, transport=transport)
        result = client.get("https://example.com/api", params={"q": "test"})
        assert result == {"ok": True}

    def test_user_agent_header(self) -> None:
        """Requests include the bookery User-Agent header."""
        transport = FakeTransport()
        client = BookeryHttpClient(min_request_interval=0.0, transport=transport)
        # Access the underlying httpx client to check headers
        assert "bookery/" in client._client.headers["user-agent"]

    def test_rate_limiting_delays_requests(self) -> None:
        """Consecutive requests are delayed by min_request_interval."""
        transport = FakeTransport()
        interval = 0.15
        client = BookeryHttpClient(min_request_interval=interval, transport=transport)

        start = time.monotonic()
        client.get("https://example.com/1")
        client.get("https://example.com/2")
        elapsed = time.monotonic() - start

        assert elapsed >= interval
        assert transport.call_count == 2

    def test_http_error_raises_metadata_fetch_error(self) -> None:
        """Non-retryable HTTP errors raise MetadataFetchError."""
        responses = [httpx.Response(404, json={"error": "not found"})]
        transport = FakeTransport(responses=responses)
        client = BookeryHttpClient(min_request_interval=0.0, transport=transport)

        with pytest.raises(MetadataFetchError, match="404"):
            client.get("https://example.com/missing")

    def test_retry_on_429(self) -> None:
        """Client retries on 429 status and succeeds on next attempt."""
        responses = [
            httpx.Response(429, json={"error": "rate limited"}),
            httpx.Response(200, json={"ok": True}),
        ]
        transport = FakeTransport(responses=responses)
        client = BookeryHttpClient(
            min_request_interval=0.0, transport=transport, retry_delay=0.01
        )

        result = client.get("https://example.com/api")
        assert result == {"ok": True}
        assert transport.call_count == 2

    def test_retry_exhausted_raises(self) -> None:
        """After max retries, raises MetadataFetchError."""
        responses = [httpx.Response(500, json={"error": "server error"})] * 4
        transport = FakeTransport(responses=responses)
        client = BookeryHttpClient(
            min_request_interval=0.0,
            transport=transport,
            max_retries=3,
            retry_delay=0.01,
        )

        with pytest.raises(MetadataFetchError, match="500"):
            client.get("https://example.com/api")
        assert transport.call_count == 4  # 1 initial + 3 retries
