# ABOUTME: Unit tests for subject extraction from Open Library API responses.
# ABOUTME: Validates that subjects are parsed from works and search endpoints.

from bookery.metadata.openlibrary_parser import (
    parse_search_results,
    parse_works_metadata,
    parse_works_subjects,
)


class TestParseWorksSubjects:
    """Tests for parse_works_subjects()."""

    def test_extracts_subjects(self) -> None:
        """parse_works_subjects returns subjects list from works data."""
        data = {"subjects": ["Fiction", "Mystery", "Italian literature"]}
        assert parse_works_subjects(data) == ["Fiction", "Mystery", "Italian literature"]

    def test_missing_subjects_returns_empty_list(self) -> None:
        """Missing subjects key returns empty list."""
        data = {"title": "A book"}
        assert parse_works_subjects(data) == []

    def test_empty_subjects_returns_empty_list(self) -> None:
        """Empty subjects list passes through."""
        data = {"subjects": []}
        assert parse_works_subjects(data) == []


class TestParseWorksMetadataSubjects:
    """Tests for subject extraction in parse_works_metadata()."""

    def test_extracts_subjects(self) -> None:
        """parse_works_metadata sets subjects on BookMetadata."""
        data = {
            "title": "Test Book",
            "key": "/works/OL123W",
            "subjects": ["Science Fiction", "Robots", "AI"],
        }
        meta = parse_works_metadata(data)
        assert meta.subjects == ["Science Fiction", "Robots", "AI"]

    def test_missing_subjects_empty(self) -> None:
        """Missing subjects defaults to empty list."""
        data = {"title": "Test Book", "key": "/works/OL123W"}
        meta = parse_works_metadata(data)
        assert meta.subjects == []


class TestParseSearchResultsSubjects:
    """Tests for subject extraction in parse_search_results()."""

    def test_extracts_subjects_from_search_doc(self) -> None:
        """Search results extract subject list from each doc."""
        data = {
            "docs": [
                {
                    "title": "Test Book",
                    "subject": ["Fiction", "Adventure", "Pirates"],
                    "key": "/works/OL1W",
                },
            ],
        }
        results = parse_search_results(data)
        assert len(results) == 1
        assert results[0].subjects == ["Fiction", "Adventure", "Pirates"]

    def test_missing_subject_key_empty(self) -> None:
        """Missing subject key results in empty subjects list."""
        data = {
            "docs": [{"title": "Test Book", "key": "/works/OL1W"}],
        }
        results = parse_search_results(data)
        assert results[0].subjects == []
