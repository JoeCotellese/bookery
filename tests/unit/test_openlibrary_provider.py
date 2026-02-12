# ABOUTME: Unit tests for OpenLibraryProvider.
# ABOUTME: Uses a FakeHttpClient to test ISBN lookup, search, scoring, and error handling.

import logging
from typing import Any
from unittest.mock import MagicMock

from bookery.metadata.http import HttpClient, MetadataFetchError
from bookery.metadata.openlibrary import OpenLibraryProvider
from tests.fixtures.openlibrary_responses import (
    AUTHOR_RESPONSE,
    EDITION_RESPONSE,
    ISBN_RESPONSE,
    SEARCH_RESPONSE,
    SEARCH_RESPONSE_EMPTY,
    SEARCH_RESPONSE_FOUR_DOCS,
    WORKS_RESPONSE_STR_DESCRIPTION,
    WORKS_RESPONSE_WITH_AUTHORS,
)


class FakeHttpClient:
    """Fake HTTP client that returns canned responses based on URL patterns."""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self._responses = responses or {}
        self.request_log: list[str] = []

    def get(self, url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        self.request_log.append(url)
        for pattern, response in self._responses.items():
            if pattern in url:
                if isinstance(response, Exception):
                    raise response
                return response
        return {}


class TestOpenLibraryProviderProtocol:
    """Tests that OpenLibraryProvider satisfies MetadataProvider."""

    def test_satisfies_protocol(self) -> None:
        """OpenLibraryProvider implements the MetadataProvider protocol."""
        from bookery.metadata.provider import MetadataProvider

        provider = OpenLibraryProvider(http_client=FakeHttpClient())
        assert isinstance(provider, MetadataProvider)

    def test_name_property(self) -> None:
        """Provider name is 'openlibrary'."""
        provider = OpenLibraryProvider(http_client=FakeHttpClient())
        assert provider.name == "openlibrary"


class TestSearchByIsbn:
    """Tests for ISBN-based lookup."""

    def test_isbn_lookup_returns_candidate(self) -> None:
        """ISBN lookup returns a scored candidate with metadata."""
        client = FakeHttpClient(
            {
                "/isbn/": ISBN_RESPONSE,
                "/works/": WORKS_RESPONSE_STR_DESCRIPTION,
                "/authors/": AUTHOR_RESPONSE,
            }
        )
        provider = OpenLibraryProvider(http_client=client)
        results = provider.search_by_isbn("9780156001311")
        assert len(results) == 1
        candidate = results[0]
        assert candidate.metadata.title == "The Name of the Rose"
        assert candidate.metadata.authors == ["Umberto Eco"]
        assert candidate.metadata.description == "A mystery set in a medieval Italian monastery."
        assert candidate.source == "openlibrary"
        assert 0.0 <= candidate.confidence <= 1.0

    def test_isbn_lookup_includes_source_id(self) -> None:
        """ISBN candidate includes the works key as source_id."""
        client = FakeHttpClient(
            {
                "/isbn/": ISBN_RESPONSE,
                "/works/": WORKS_RESPONSE_STR_DESCRIPTION,
                "/authors/": AUTHOR_RESPONSE,
            }
        )
        provider = OpenLibraryProvider(http_client=client)
        results = provider.search_by_isbn("9780156001311")
        assert results[0].source_id == "/works/OL456W"

    def test_isbn_lookup_network_error_returns_empty(self, caplog: Any) -> None:
        """Network errors during ISBN lookup return empty list and log warning."""
        client = FakeHttpClient({"/isbn/": MetadataFetchError("connection refused")})
        provider = OpenLibraryProvider(http_client=client)
        with caplog.at_level(logging.WARNING):
            results = provider.search_by_isbn("9780156001311")
        assert results == []
        assert any("connection refused" in r.message for r in caplog.records)

    def test_isbn_lookup_no_works_key(self) -> None:
        """ISBN response without works key still returns a candidate."""
        data = {**ISBN_RESPONSE, "works": []}
        client = FakeHttpClient({"/isbn/": data})
        provider = OpenLibraryProvider(http_client=client)
        results = provider.search_by_isbn("9780156001311")
        assert len(results) == 1
        assert results[0].metadata.title == "The Name of the Rose"

    def test_isbn_lookup_no_author_key(self) -> None:
        """ISBN response without authors key still returns a candidate."""
        data = {**ISBN_RESPONSE, "authors": []}
        client = FakeHttpClient(
            {
                "/isbn/": data,
                "/works/": WORKS_RESPONSE_STR_DESCRIPTION,
            }
        )
        provider = OpenLibraryProvider(http_client=client)
        results = provider.search_by_isbn("9780156001311")
        assert len(results) == 1
        assert results[0].metadata.authors == []

    def test_isbn_lookup_strips_hyphens(self) -> None:
        """Hyphenated ISBN is cleaned before sending to API."""
        client = FakeHttpClient(
            {
                "/isbn/9780345529718": ISBN_RESPONSE,
                "/works/": WORKS_RESPONSE_STR_DESCRIPTION,
                "/authors/": AUTHOR_RESPONSE,
            }
        )
        provider = OpenLibraryProvider(http_client=client)
        results = provider.search_by_isbn("978-0-345-52971-8")
        assert len(results) == 1
        # Verify the URL sent to the client had the clean ISBN
        assert any("9780345529718" in url for url in client.request_log)
        assert not any("978-0-345-52971-8" in url for url in client.request_log)

    def test_isbn_lookup_strips_spaces(self) -> None:
        """ISBN with spaces is cleaned before sending to API."""
        client = FakeHttpClient(
            {
                "/isbn/9780345529718": ISBN_RESPONSE,
                "/works/": WORKS_RESPONSE_STR_DESCRIPTION,
                "/authors/": AUTHOR_RESPONSE,
            }
        )
        provider = OpenLibraryProvider(http_client=client)
        results = provider.search_by_isbn("978 0 345 52971 8")
        assert len(results) == 1
        assert any("9780345529718" in url for url in client.request_log)


class TestSearchByTitleAuthor:
    """Tests for title/author search."""

    def test_search_returns_scored_candidates(self) -> None:
        """Title/author search returns scored candidates sorted by confidence."""
        client = FakeHttpClient({"/search.json": SEARCH_RESPONSE})
        provider = OpenLibraryProvider(http_client=client)
        results = provider.search_by_title_author("The Name of the Rose", "Umberto Eco")
        assert len(results) == 2
        # Should be sorted by confidence descending
        assert results[0].confidence >= results[1].confidence

    def test_search_empty_results(self) -> None:
        """Empty search returns empty list."""
        client = FakeHttpClient({"/search.json": SEARCH_RESPONSE_EMPTY})
        provider = OpenLibraryProvider(http_client=client)
        results = provider.search_by_title_author("Nonexistent Book")
        assert results == []

    def test_search_network_error_returns_empty(self, caplog: Any) -> None:
        """Network errors during search return empty list and log warning."""
        client = FakeHttpClient({"/search.json": MetadataFetchError("timeout")})
        provider = OpenLibraryProvider(http_client=client)
        with caplog.at_level(logging.WARNING):
            results = provider.search_by_title_author("Test")
        assert results == []
        assert any("timeout" in r.message for r in caplog.records)

    def test_search_passes_correct_params(self) -> None:
        """Search sends title and author as query parameters."""
        mock_client = MagicMock(spec=HttpClient)
        mock_client.get.return_value = SEARCH_RESPONSE_EMPTY
        provider = OpenLibraryProvider(http_client=mock_client)
        provider.search_by_title_author("Rose", "Eco")
        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args
        params = call_args[1].get("params") or call_args[0][1]
        assert params["title"] == "Rose"
        assert params["author"] == "Eco"

    def test_search_without_author(self) -> None:
        """Search with title only omits author parameter."""
        mock_client = MagicMock(spec=HttpClient)
        mock_client.get.return_value = SEARCH_RESPONSE_EMPTY
        provider = OpenLibraryProvider(http_client=mock_client)
        provider.search_by_title_author("Rose")
        call_args = mock_client.get.call_args
        params = call_args[1].get("params") or call_args[0][1]
        assert "author" not in params

    def test_search_enriches_top_candidates_with_descriptions(self) -> None:
        """Top 3 search candidates are enriched with descriptions from works endpoint."""
        works_responses = {
            "OL456W": {"description": "Description for OL456W."},
            "OL789W": {"description": "Description for OL789W."},
            "OL101W": {"description": "Description for OL101W."},
        }

        def fake_get(url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
            if "/search.json" in url:
                return SEARCH_RESPONSE_FOUR_DOCS
            for key, data in works_responses.items():
                if key in url:
                    return data
            return {}

        client = MagicMock(spec=HttpClient)
        client.get.side_effect = fake_get
        provider = OpenLibraryProvider(http_client=client)
        results = provider.search_by_title_author("The Name of the Rose", "Umberto Eco")

        assert len(results) == 4
        # Top 3 should have descriptions
        assert results[0].metadata.description is not None
        assert results[1].metadata.description is not None
        assert results[2].metadata.description is not None

    def test_search_does_not_enrich_beyond_limit(self) -> None:
        """4th candidate description stays None when enrichment limit is 3."""
        works_responses = {
            "OL456W": {"description": "Desc 1."},
            "OL789W": {"description": "Desc 2."},
            "OL101W": {"description": "Desc 3."},
            "OL202W": {"description": "Desc 4."},
        }

        def fake_get(url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
            if "/search.json" in url:
                return SEARCH_RESPONSE_FOUR_DOCS
            for key, data in works_responses.items():
                if key in url:
                    return data
            return {}

        client = MagicMock(spec=HttpClient)
        client.get.side_effect = fake_get
        provider = OpenLibraryProvider(http_client=client)
        results = provider.search_by_title_author("The Name of the Rose", "Umberto Eco")

        # 4th candidate should NOT have been enriched
        assert results[3].metadata.description is None


class TestSubtitleRetry:
    """Tests for subtitle-stripping retry logic in title/author search."""

    def test_retry_fires_on_empty_results_with_subtitle(self) -> None:
        """When initial search returns empty and title has subtitle, retry without it."""
        call_log: list[dict[str, str] | None] = []

        def fake_get(url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
            if "/search.json" in url:
                call_log.append(params)
                # First call (with subtitle) returns empty, second returns results
                if params and ":" in params.get("title", ""):
                    return SEARCH_RESPONSE_EMPTY
                return SEARCH_RESPONSE
            return {}

        client = MagicMock(spec=HttpClient)
        client.get.side_effect = fake_get
        provider = OpenLibraryProvider(http_client=client)
        results = provider.search_by_title_author("The King's Deception: A Novel")

        assert len(results) == 2
        assert len(call_log) == 2
        assert call_log[0]["title"] == "The King's Deception: A Novel"
        assert call_log[1]["title"] == "The King's Deception"

    def test_no_retry_when_results_found(self) -> None:
        """No retry when initial search returns results."""
        call_count = 0

        def fake_get(url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
            nonlocal call_count
            if "/search.json" in url:
                call_count += 1
                return SEARCH_RESPONSE
            return {}

        client = MagicMock(spec=HttpClient)
        client.get.side_effect = fake_get
        provider = OpenLibraryProvider(http_client=client)
        results = provider.search_by_title_author("The Name of the Rose: including Postscript")

        assert len(results) > 0
        assert call_count == 1

    def test_no_retry_without_subtitle_pattern(self) -> None:
        """No retry when title doesn't have a subtitle pattern."""
        call_count = 0

        def fake_get(url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
            nonlocal call_count
            if "/search.json" in url:
                call_count += 1
                return SEARCH_RESPONSE_EMPTY
            return {}

        client = MagicMock(spec=HttpClient)
        client.get.side_effect = fake_get
        provider = OpenLibraryProvider(http_client=client)
        results = provider.search_by_title_author("Nonexistent Book")

        assert results == []
        assert call_count == 1


class TestStripSubtitle:
    """Tests for _strip_subtitle helper."""

    def test_strips_colon_subtitle(self) -> None:
        """Strips 'A Novel' subtitle after colon."""
        from bookery.metadata.openlibrary import _strip_subtitle

        assert _strip_subtitle("The King's Deception: A Novel") == "The King's Deception"

    def test_strips_long_subtitle(self) -> None:
        """Strips longer subtitle after colon."""
        from bookery.metadata.openlibrary import _strip_subtitle

        assert _strip_subtitle("The Paris Vendetta: A Cotton Malone Novel") == "The Paris Vendetta"

    def test_returns_none_without_colon(self) -> None:
        """Returns None when no subtitle pattern present."""
        from bookery.metadata.openlibrary import _strip_subtitle

        assert _strip_subtitle("The Templar Legacy") is None

    def test_returns_none_for_colon_without_space(self) -> None:
        """Colon not followed by space is not a subtitle separator."""
        from bookery.metadata.openlibrary import _strip_subtitle

        assert _strip_subtitle("Title:NoSpace") is None

    def test_returns_none_when_result_same_as_input(self) -> None:
        """Returns None if stripping produces the same string."""
        from bookery.metadata.openlibrary import _strip_subtitle

        # Edge case: only whitespace after would result in same after strip
        assert _strip_subtitle("Just a title") is None


class TestLookupByUrl:
    """Tests for URL-based lookup."""

    def test_lookup_by_url_with_edition(self) -> None:
        """URL with edition key fetches edition + works + author data."""

        def fake_get(url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
            if "/books/OL7914753M" in url:
                return EDITION_RESPONSE
            if "/works/OL456W" in url:
                return WORKS_RESPONSE_STR_DESCRIPTION
            if "/authors/OL123A" in url:
                return AUTHOR_RESPONSE
            return {}

        client = MagicMock(spec=HttpClient)
        client.get.side_effect = fake_get
        provider = OpenLibraryProvider(http_client=client)

        url = "https://openlibrary.org/works/OL5735304W/The_Templar_Legacy?edition=key%3A/books/OL7914753M"
        result = provider.lookup_by_url(url)

        assert result is not None
        assert result.metadata.title == "The Name of the Rose"
        assert result.metadata.authors == ["Umberto Eco"]
        assert result.metadata.description == "A mystery set in a medieval Italian monastery."
        assert result.confidence == 1.0
        assert result.source == "openlibrary"

    def test_lookup_by_url_works_only(self) -> None:
        """URL with only works key fetches works + author data."""

        def fake_get(url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
            if "/works/OL456W" in url:
                return WORKS_RESPONSE_WITH_AUTHORS
            if "/authors/OL123A" in url:
                return AUTHOR_RESPONSE
            return {}

        client = MagicMock(spec=HttpClient)
        client.get.side_effect = fake_get
        provider = OpenLibraryProvider(http_client=client)

        url = "https://openlibrary.org/works/OL456W/The_Name_of_the_Rose"
        result = provider.lookup_by_url(url)

        assert result is not None
        assert result.metadata.title == "The Name of the Rose"
        assert result.metadata.authors == ["Umberto Eco"]
        assert result.metadata.description == "A mystery set in a medieval Italian monastery."
        assert result.confidence == 1.0
        assert result.source == "openlibrary"
        assert result.source_id == "/works/OL456W"

    def test_lookup_by_url_invalid_url_returns_none(self) -> None:
        """Garbage URL returns None."""
        client = FakeHttpClient()
        provider = OpenLibraryProvider(http_client=client)
        assert provider.lookup_by_url("not-a-url") is None
        assert provider.lookup_by_url("https://google.com") is None
        assert provider.lookup_by_url("https://openlibrary.org/search") is None

    def test_lookup_by_url_fetch_error_returns_none(self) -> None:
        """HTTP error during lookup returns None."""
        client = FakeHttpClient({"/works/": MetadataFetchError("server error")})
        provider = OpenLibraryProvider(http_client=client)
        url = "https://openlibrary.org/works/OL456W/Title"
        assert provider.lookup_by_url(url) is None
