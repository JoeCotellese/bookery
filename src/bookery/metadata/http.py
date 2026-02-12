# ABOUTME: HTTP client abstraction for metadata provider API calls.
# ABOUTME: Provides rate limiting, retry with backoff, and injectable transport for testing.

import logging
import time
from typing import Any, Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class MetadataFetchError(Exception):
    """Raised when an HTTP request to a metadata provider fails."""


@runtime_checkable
class HttpClient(Protocol):
    """Protocol for HTTP GET operations against metadata APIs."""

    def get(self, url: str, params: dict[str, str] | None = None) -> dict[str, Any]: ...


class BookeryHttpClient:
    """HTTP client with rate limiting and retry for metadata API calls.

    Wraps httpx.Client with configurable request intervals and retry logic
    for transient failures (429, 5xx).
    """

    def __init__(
        self,
        *,
        min_request_interval: float = 0.1,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        client_kwargs: dict[str, Any] = {
            "headers": {"User-Agent": "bookery/0.1.0"},
            "timeout": 30.0,
        }
        if transport is not None:
            client_kwargs["transport"] = transport
        self._client = httpx.Client(**client_kwargs)
        self._min_interval = min_request_interval
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._last_request_time: float = 0.0

    def get(self, url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        """Send a GET request with rate limiting and retry.

        Args:
            url: The URL to request.
            params: Optional query parameters.

        Returns:
            Parsed JSON response body.

        Raises:
            MetadataFetchError: On non-retryable HTTP errors or exhausted retries.
        """
        self._rate_limit()

        attempts = 1 + self._max_retries
        last_status = 0
        for attempt in range(attempts):
            try:
                response = self._client.get(url, params=params)
                last_status = response.status_code
            except httpx.HTTPError as exc:
                raise MetadataFetchError(f"Request failed: {url}: {exc}") from exc

            if response.status_code == 200:
                return response.json()

            if response.status_code not in _RETRYABLE_STATUS_CODES:
                raise MetadataFetchError(
                    f"HTTP {response.status_code} from {url}"
                )

            if attempt < attempts - 1:
                delay = self._retry_delay * (2**attempt)
                logger.warning(
                    "HTTP %d from %s, retrying in %.1fs (attempt %d/%d)",
                    response.status_code,
                    url,
                    delay,
                    attempt + 1,
                    self._max_retries,
                )
                time.sleep(delay)

        raise MetadataFetchError(f"HTTP {last_status} from {url} after {attempts} attempts")

    def _rate_limit(self) -> None:
        """Sleep if needed to maintain minimum interval between requests."""
        if self._min_interval <= 0:
            return
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < self._min_interval and self._last_request_time > 0:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.monotonic()
