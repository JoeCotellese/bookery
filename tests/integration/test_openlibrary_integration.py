# ABOUTME: Integration tests for the OpenLibraryProvider pipeline.
# ABOUTME: Tests full flow: provider → parsing → scoring → ranked candidates with FakeHttpClient.

from typing import Any

from bookery.metadata.openlibrary import OpenLibraryProvider
from tests.fixtures.openlibrary_responses import (
    AUTHOR_RESPONSE,
    ISBN_RESPONSE,
    SEARCH_RESPONSE,
    SEARCH_RESPONSE_EMPTY,
    WORKS_RESPONSE_STR_DESCRIPTION,
)


class FakeHttpClient:
    """Fake HTTP client returning canned responses keyed by URL substrings."""

    def __init__(self, responses: dict[str, Any]) -> None:
        self._responses = responses

    def get(self, url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        for pattern, response in self._responses.items():
            if pattern in url:
                return response
        return {}


class TestIsbnPipeline:
    """Integration tests for the ISBN lookup pipeline."""

    def test_isbn_produces_enriched_candidate(self) -> None:
        """ISBN lookup fetches edition → works → authors and merges into one candidate."""
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
        meta = results[0].metadata
        assert meta.title == "The Name of the Rose"
        assert meta.authors == ["Umberto Eco"]
        assert meta.publisher == "Harcourt"
        assert meta.isbn == "9780156001311"
        assert meta.description == "A mystery set in a medieval Italian monastery."
        assert results[0].source == "openlibrary"

    def test_isbn_candidate_has_high_confidence(self) -> None:
        """ISBN matches have confidence of 1.0."""
        client = FakeHttpClient(
            {
                "/isbn/": ISBN_RESPONSE,
                "/works/": WORKS_RESPONSE_STR_DESCRIPTION,
                "/authors/": AUTHOR_RESPONSE,
            }
        )
        provider = OpenLibraryProvider(http_client=client)
        results = provider.search_by_isbn("9780156001311")
        assert results[0].confidence == 1.0

    def test_hyphenated_isbn_resolves_through_pipeline(self) -> None:
        """Hyphenated ISBN is cleaned and resolves to enriched candidate."""
        client = FakeHttpClient(
            {
                "/isbn/9780156001311": ISBN_RESPONSE,
                "/works/": WORKS_RESPONSE_STR_DESCRIPTION,
                "/authors/": AUTHOR_RESPONSE,
            }
        )
        provider = OpenLibraryProvider(http_client=client)
        results = provider.search_by_isbn("978-0-156-00131-1")

        assert len(results) == 1
        meta = results[0].metadata
        assert meta.title == "The Name of the Rose"
        assert meta.authors == ["Umberto Eco"]


class TestSubtitleRetryPipeline:
    """Integration tests for subtitle retry in search pipeline."""

    def test_subtitle_retry_finds_book_through_pipeline(self) -> None:
        """Subtitle retry produces scored candidates through the full pipeline."""

        def fake_get(url: str, params: dict[str, str] | None = None) -> Any:
            if "/search.json" in url:
                if params and ":" in params.get("title", ""):
                    return SEARCH_RESPONSE_EMPTY
                return SEARCH_RESPONSE
            return {}

        client = FakeHttpClient({})
        client.get = fake_get  # type: ignore[assignment]
        provider = OpenLibraryProvider(http_client=client)
        results = provider.search_by_title_author("The Name of the Rose: A Novel", "Umberto Eco")

        assert len(results) > 0
        assert results[0].metadata.title == "The Name of the Rose"
        assert results[0].confidence > 0.0


class TestSearchPipeline:
    """Integration tests for the search pipeline."""

    def test_search_produces_scored_ranked_candidates(self) -> None:
        """Search returns candidates scored against the query and sorted."""
        client = FakeHttpClient({"/search.json": SEARCH_RESPONSE})
        provider = OpenLibraryProvider(http_client=client)
        results = provider.search_by_title_author("The Name of the Rose", "Umberto Eco")

        assert len(results) == 2
        # First result should be the closer title match
        assert results[0].metadata.title == "The Name of the Rose"
        assert results[0].confidence >= results[1].confidence

    def test_search_scoring_reflects_title_similarity(self) -> None:
        """Exact title match scores higher than partial match."""
        client = FakeHttpClient({"/search.json": SEARCH_RESPONSE})
        provider = OpenLibraryProvider(http_client=client)
        results = provider.search_by_title_author("The Name of the Rose", "Umberto Eco")

        exact = results[0]  # "The Name of the Rose"
        partial = results[1]  # "The Name of the Rose: including Postscript"
        assert exact.confidence > partial.confidence

    def test_all_candidates_have_source_info(self) -> None:
        """Every candidate includes source and source_id."""
        client = FakeHttpClient({"/search.json": SEARCH_RESPONSE})
        provider = OpenLibraryProvider(http_client=client)
        results = provider.search_by_title_author("The Name of the Rose")
        for candidate in results:
            assert candidate.source == "openlibrary"
            assert candidate.source_id != ""
