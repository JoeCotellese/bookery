# ABOUTME: Unit tests for BookMetadata to/from database row mapping.
# ABOUTME: Validates JSON serialization, round-trips, null handling, and BookRecord.

import json
from pathlib import Path

from bookery.db.mapping import BookRecord, metadata_to_row, row_to_metadata
from bookery.metadata.types import BookMetadata


class TestMetadataToRow:
    """Tests for metadata_to_row conversion."""

    def test_includes_all_fields(self) -> None:
        """Row dict contains all expected keys."""
        meta = BookMetadata(title="Test Book")
        row = metadata_to_row(meta, file_hash="abc123")

        expected_keys = {
            "title", "authors", "author_sort", "language", "publisher",
            "isbn", "description", "series", "series_index", "identifiers",
            "source_path", "output_path", "file_hash",
        }
        assert expected_keys == set(row.keys())

    def test_authors_serialized_as_json(self) -> None:
        """Authors list is stored as a JSON array string."""
        meta = BookMetadata(title="Test", authors=["Author A", "Author B"])
        row = metadata_to_row(meta, file_hash="abc")
        assert row["authors"] == '["Author A", "Author B"]'
        assert json.loads(row["authors"]) == ["Author A", "Author B"]

    def test_identifiers_serialized_as_json(self) -> None:
        """Identifiers dict is stored as a JSON object string."""
        meta = BookMetadata(title="Test", identifiers={"ol_work": "OL123W"})
        row = metadata_to_row(meta, file_hash="abc")
        assert json.loads(row["identifiers"]) == {"ol_work": "OL123W"}

    def test_empty_authors_serialized_as_empty_list(self) -> None:
        """Empty authors list serializes to '[]'."""
        meta = BookMetadata(title="Test")
        row = metadata_to_row(meta, file_hash="abc")
        assert row["authors"] == "[]"

    def test_empty_identifiers_serialized_as_empty_dict(self) -> None:
        """Empty identifiers dict serializes to '{}'."""
        meta = BookMetadata(title="Test")
        row = metadata_to_row(meta, file_hash="abc")
        assert row["identifiers"] == "{}"

    def test_file_hash_included(self) -> None:
        """file_hash is passed through to the row dict."""
        meta = BookMetadata(title="Test")
        row = metadata_to_row(meta, file_hash="deadbeef")
        assert row["file_hash"] == "deadbeef"

    def test_source_path_stored_as_string(self) -> None:
        """Path is converted to string for storage."""
        meta = BookMetadata(title="Test", source_path=Path("/books/test.epub"))
        row = metadata_to_row(meta, file_hash="abc")
        assert row["source_path"] == "/books/test.epub"

    def test_output_path_stored_as_string(self) -> None:
        """Output path is converted to string."""
        meta = BookMetadata(title="Test")
        row = metadata_to_row(meta, file_hash="abc", output_path=Path("/out/test.epub"))
        assert row["output_path"] == "/out/test.epub"

    def test_output_path_none_by_default(self) -> None:
        """Output path is None when not provided."""
        meta = BookMetadata(title="Test")
        row = metadata_to_row(meta, file_hash="abc")
        assert row["output_path"] is None

    def test_cover_image_not_stored(self) -> None:
        """cover_image binary data is excluded from DB rows."""
        meta = BookMetadata(title="Test", cover_image=b"fake png data")
        row = metadata_to_row(meta, file_hash="abc")
        assert "cover_image" not in row


class TestRowToMetadata:
    """Tests for row_to_metadata conversion."""

    def test_deserializes_json_authors(self) -> None:
        """JSON author string is deserialized to a list."""
        row = {
            "title": "Test", "authors": '["A", "B"]', "author_sort": None,
            "language": None, "publisher": None, "isbn": None,
            "description": None, "series": None, "series_index": None,
            "identifiers": "{}", "source_path": "/test.epub",
        }
        meta = row_to_metadata(row)
        assert meta.authors == ["A", "B"]

    def test_deserializes_json_identifiers(self) -> None:
        """JSON identifiers string is deserialized to a dict."""
        row = {
            "title": "Test", "authors": "[]", "author_sort": None,
            "language": None, "publisher": None, "isbn": None,
            "description": None, "series": None, "series_index": None,
            "identifiers": '{"key": "val"}', "source_path": "/test.epub",
        }
        meta = row_to_metadata(row)
        assert meta.identifiers == {"key": "val"}

    def test_handles_null_fields(self) -> None:
        """NULL columns map to None on BookMetadata."""
        row = {
            "title": "Test", "authors": "[]", "author_sort": None,
            "language": None, "publisher": None, "isbn": None,
            "description": None, "series": None, "series_index": None,
            "identifiers": "{}", "source_path": "/test.epub",
        }
        meta = row_to_metadata(row)
        assert meta.language is None
        assert meta.publisher is None
        assert meta.isbn is None
        assert meta.description is None

    def test_source_path_restored_as_path(self) -> None:
        """source_path string is converted back to a Path."""
        row = {
            "title": "Test", "authors": "[]", "author_sort": None,
            "language": None, "publisher": None, "isbn": None,
            "description": None, "series": None, "series_index": None,
            "identifiers": "{}", "source_path": "/books/test.epub",
        }
        meta = row_to_metadata(row)
        assert meta.source_path == Path("/books/test.epub")


class TestRoundTrip:
    """Tests for full metadata -> row -> metadata round-trip."""

    def test_full_roundtrip(self) -> None:
        """A fully-populated BookMetadata survives a round-trip through row mapping."""
        original = BookMetadata(
            title="The Name of the Rose",
            authors=["Umberto Eco"],
            author_sort="Eco, Umberto",
            language="eng",
            publisher="Harcourt",
            isbn="9780156001311",
            description="A mystery in a medieval monastery.",
            series="None Series",
            series_index=1.0,
            identifiers={"openlibrary_work": "OL123W"},
            source_path=Path("/books/rose.epub"),
        )

        row = metadata_to_row(original, file_hash="abc123")
        restored = row_to_metadata(row)

        assert restored.title == original.title
        assert restored.authors == original.authors
        assert restored.author_sort == original.author_sort
        assert restored.language == original.language
        assert restored.publisher == original.publisher
        assert restored.isbn == original.isbn
        assert restored.description == original.description
        assert restored.series == original.series
        assert restored.series_index == original.series_index
        assert restored.identifiers == original.identifiers
        assert restored.source_path == original.source_path


class TestBookRecord:
    """Tests for the BookRecord dataclass."""

    def test_book_record_has_db_fields(self) -> None:
        """BookRecord wraps BookMetadata plus DB-specific fields."""
        meta = BookMetadata(title="Test")
        record = BookRecord(
            id=1,
            metadata=meta,
            file_hash="abc123",
            source_path=Path("/test.epub"),
            output_path=None,
            date_added="2024-01-01T00:00:00",
            date_modified="2024-01-01T00:00:00",
        )
        assert record.id == 1
        assert record.metadata.title == "Test"
        assert record.file_hash == "abc123"
        assert record.output_path is None
