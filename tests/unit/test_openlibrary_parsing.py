# ABOUTME: Unit tests for Open Library API response parsing functions.
# ABOUTME: Validates conversion from OL JSON structures to BookMetadata.

from bookery.metadata.openlibrary_parser import (
    build_cover_url,
    parse_author_name,
    parse_isbn_response,
    parse_search_results,
    parse_works_metadata,
    parse_works_response,
)
from tests.fixtures.openlibrary_responses import (
    AUTHOR_RESPONSE,
    ISBN_RESPONSE,
    SEARCH_RESPONSE,
    SEARCH_RESPONSE_EMPTY,
    SEARCH_RESPONSE_MINIMAL,
    WORKS_RESPONSE_DICT_DESCRIPTION,
    WORKS_RESPONSE_NO_DESCRIPTION,
    WORKS_RESPONSE_STR_DESCRIPTION,
    WORKS_RESPONSE_WITH_AUTHORS,
)


class TestParseIsbnResponse:
    """Tests for parse_isbn_response."""

    def test_extracts_title(self) -> None:
        """Title is extracted from ISBN response."""
        meta = parse_isbn_response(ISBN_RESPONSE)
        assert meta.title == "The Name of the Rose"

    def test_extracts_publisher(self) -> None:
        """First publisher is extracted."""
        meta = parse_isbn_response(ISBN_RESPONSE)
        assert meta.publisher == "Harcourt"

    def test_extracts_isbn13(self) -> None:
        """ISBN-13 is preferred over ISBN-10."""
        meta = parse_isbn_response(ISBN_RESPONSE)
        assert meta.isbn == "9780156001311"

    def test_extracts_language(self) -> None:
        """Language code is extracted from language key."""
        meta = parse_isbn_response(ISBN_RESPONSE)
        assert meta.language == "eng"

    def test_extracts_works_key(self) -> None:
        """Works key is stored in identifiers."""
        meta = parse_isbn_response(ISBN_RESPONSE)
        assert meta.identifiers.get("openlibrary_work") == "/works/OL456W"

    def test_missing_fields_handled(self) -> None:
        """Minimal response doesn't crash."""
        data = {"title": "Bare Minimum"}
        meta = parse_isbn_response(data)
        assert meta.title == "Bare Minimum"
        assert meta.isbn is None
        assert meta.publisher is None


class TestParseWorksResponse:
    """Tests for parse_works_response."""

    def test_string_description(self) -> None:
        """Description as plain string is returned."""
        desc = parse_works_response(WORKS_RESPONSE_STR_DESCRIPTION)
        assert desc == "A mystery set in a medieval Italian monastery."

    def test_dict_description(self) -> None:
        """Description as {type, value} dict extracts the value."""
        desc = parse_works_response(WORKS_RESPONSE_DICT_DESCRIPTION)
        assert desc == "A mystery set in a medieval Italian monastery."

    def test_missing_description(self) -> None:
        """Returns None when description is absent."""
        desc = parse_works_response(WORKS_RESPONSE_NO_DESCRIPTION)
        assert desc is None


class TestParseAuthorName:
    """Tests for parse_author_name."""

    def test_extracts_name(self) -> None:
        """Author name is extracted from author response."""
        name = parse_author_name(AUTHOR_RESPONSE)
        assert name == "Umberto Eco"

    def test_missing_name_returns_unknown(self) -> None:
        """Returns 'Unknown' when name field is absent."""
        name = parse_author_name({"key": "/authors/OL123A"})
        assert name == "Unknown"


class TestParseSearchResults:
    """Tests for parse_search_results."""

    def test_parses_multiple_results(self) -> None:
        """Multiple search results are parsed into BookMetadata list."""
        results = parse_search_results(SEARCH_RESPONSE)
        assert len(results) == 2
        assert results[0].title == "The Name of the Rose"
        assert results[1].title == "The Name of the Rose: including Postscript"

    def test_extracts_author_from_search(self) -> None:
        """Author names are extracted from search results."""
        results = parse_search_results(SEARCH_RESPONSE)
        assert results[0].authors == ["Umberto Eco"]

    def test_empty_search(self) -> None:
        """Empty search returns empty list."""
        results = parse_search_results(SEARCH_RESPONSE_EMPTY)
        assert results == []

    def test_minimal_search_result(self) -> None:
        """Search result with only title and key still parses."""
        results = parse_search_results(SEARCH_RESPONSE_MINIMAL)
        assert len(results) == 1
        assert results[0].title == "Minimal Book"
        assert results[0].authors == []


class TestParseWorksMetadata:
    """Tests for parse_works_metadata."""

    def test_extracts_title_and_description(self) -> None:
        """Title and description are extracted from works response."""
        meta = parse_works_metadata(WORKS_RESPONSE_WITH_AUTHORS)
        assert meta.title == "The Name of the Rose"
        assert meta.description == "A mystery set in a medieval Italian monastery."

    def test_extracts_author_keys(self) -> None:
        """Author keys are stored in identifiers for later resolution."""
        meta = parse_works_metadata(WORKS_RESPONSE_WITH_AUTHORS)
        assert meta.identifiers.get("openlibrary_work") == "/works/OL456W"
        # Author keys stored for later enrichment
        assert meta.identifiers.get("openlibrary_author_keys") == "/authors/OL123A"

    def test_missing_description(self) -> None:
        """Works response without description returns None description."""
        meta = parse_works_metadata(WORKS_RESPONSE_NO_DESCRIPTION)
        assert meta.title == "The Name of the Rose"
        assert meta.description is None

    def test_dict_description(self) -> None:
        """Works response with dict-style description extracts the value."""
        meta = parse_works_metadata(WORKS_RESPONSE_DICT_DESCRIPTION)
        assert meta.description == "A mystery set in a medieval Italian monastery."


class TestBuildCoverUrl:
    """Tests for build_cover_url."""

    def test_default_large_size(self) -> None:
        """Default cover URL uses large size."""
        url = build_cover_url("9780156001311")
        assert "9780156001311" in url
        assert "-L." in url

    def test_custom_size(self) -> None:
        """Custom size parameter is used in URL."""
        url = build_cover_url("9780156001311", size="M")
        assert "-M." in url
