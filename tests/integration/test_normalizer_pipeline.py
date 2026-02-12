# ABOUTME: Integration tests for normalizer in the match pipeline.
# ABOUTME: Verifies normalized metadata produces valid search queries with FakeHttpClient.

from typing import Any

from bookery.metadata import BookMetadata
from bookery.metadata.normalizer import normalize_metadata
from bookery.metadata.openlibrary import OpenLibraryProvider
from tests.fixtures.openlibrary_responses import SEARCH_RESPONSE


class FakeHttpClient:
    """Fake HTTP client that records search queries for verification."""

    def __init__(self, responses: dict[str, Any]) -> None:
        self._responses = responses
        self.requests: list[tuple[str, dict[str, str] | None]] = []

    def get(self, url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        self.requests.append((url, params))
        for pattern, response in self._responses.items():
            if pattern in url:
                return response
        return {}


class TestNormalizerPipeline:
    """Integration tests for normalizer with provider search."""

    def test_normalized_metadata_produces_space_separated_query(self) -> None:
        """Normalized mangled title becomes a space-separated search query."""
        meta = BookMetadata(title="SteveBerry-TheTemplarLegacy")
        result = normalize_metadata(meta)

        assert result.was_modified is True
        assert " " in result.normalized.title
        # Title should not contain the original mangled form
        assert "SteveBerry" not in result.normalized.title

    def test_normalized_metadata_works_with_provider(self) -> None:
        """Normalized metadata can be searched via OpenLibraryProvider."""
        meta = BookMetadata(title="SteveBerry-TheTemplarLegacy")
        result = normalize_metadata(meta)

        client = FakeHttpClient({"/search.json": SEARCH_RESPONSE})
        provider = OpenLibraryProvider(http_client=client)

        candidates = provider.search_by_title_author(
            result.normalized.title,
            result.normalized.author or None,
        )

        # Provider should receive a request and return candidates
        assert len(client.requests) > 0
        assert len(candidates) > 0

    def test_clean_metadata_skips_normalization_in_pipeline(self) -> None:
        """Clean metadata passes through normalization unchanged."""
        meta = BookMetadata(
            title="The Name of the Rose",
            authors=["Umberto Eco"],
        )
        result = normalize_metadata(meta)

        assert result.was_modified is False
        assert result.normalized is meta

        # Still works with provider
        client = FakeHttpClient({"/search.json": SEARCH_RESPONSE})
        provider = OpenLibraryProvider(http_client=client)
        candidates = provider.search_by_title_author(
            result.normalized.title,
            result.normalized.author or None,
        )
        assert len(candidates) > 0

    def test_normalized_query_params_are_clean(self) -> None:
        """The actual query parameters sent to OL contain properly spaced text."""
        meta = BookMetadata(title="TheTemplarLegacy", authors=["Unknown"])
        result = normalize_metadata(meta)

        client = FakeHttpClient({"/search.json": SEARCH_RESPONSE})
        provider = OpenLibraryProvider(http_client=client)
        provider.search_by_title_author(
            result.normalized.title,
            result.normalized.author or None,
        )

        # Check the query params sent to the fake client
        assert len(client.requests) > 0
        _url, params = client.requests[0]
        assert params is not None
        # The title query should contain spaces, not CamelCase
        assert "TheTemplarLegacy" not in params.get("title", "")
