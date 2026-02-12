# ABOUTME: Unit tests for EPUB metadata extraction.
# ABOUTME: Tests reading metadata from valid, minimal, and corrupt EPUB files.

from pathlib import Path

import pytest

from bookery.formats.epub import read_epub_metadata
from bookery.metadata import BookMetadata


class TestReadEpubMetadata:
    """Tests for EPUB metadata extraction."""

    def test_extracts_title(self, sample_epub: Path) -> None:
        """Extracts the title from a valid EPUB."""
        meta = read_epub_metadata(sample_epub)
        assert meta.title == "The Name of the Rose"

    def test_extracts_author(self, sample_epub: Path) -> None:
        """Extracts the author from a valid EPUB."""
        meta = read_epub_metadata(sample_epub)
        assert meta.authors == ["Umberto Eco"]
        assert meta.author == "Umberto Eco"

    def test_extracts_language(self, sample_epub: Path) -> None:
        """Extracts the language from a valid EPUB."""
        meta = read_epub_metadata(sample_epub)
        assert meta.language == "en"

    def test_extracts_publisher(self, sample_epub: Path) -> None:
        """Extracts the publisher from a valid EPUB."""
        meta = read_epub_metadata(sample_epub)
        assert meta.publisher == "Harcourt"

    def test_extracts_description(self, sample_epub: Path) -> None:
        """Extracts the description from a valid EPUB."""
        meta = read_epub_metadata(sample_epub)
        assert meta.description == "A mystery set in a medieval monastery."

    def test_extracts_identifier_as_isbn(self, sample_epub: Path) -> None:
        """Extracts the identifier and stores it."""
        meta = read_epub_metadata(sample_epub)
        assert "test-isbn-978-0-123456-47-2" in meta.identifiers.values()

    def test_sets_source_path(self, sample_epub: Path) -> None:
        """Sets the source_path to the file that was read."""
        meta = read_epub_metadata(sample_epub)
        assert meta.source_path == sample_epub

    def test_minimal_epub_has_title(self, minimal_epub: Path) -> None:
        """A minimal EPUB with only basic metadata still extracts a title."""
        meta = read_epub_metadata(minimal_epub)
        assert meta.title == "Untitled Book"

    def test_minimal_epub_has_empty_optional_fields(self, minimal_epub: Path) -> None:
        """A minimal EPUB returns None for fields not present."""
        meta = read_epub_metadata(minimal_epub)
        assert meta.publisher is None
        assert meta.description is None
        assert meta.isbn is None
        assert meta.series is None

    def test_corrupt_epub_raises(self, corrupt_epub: Path) -> None:
        """A corrupt file raises an EpubReadError."""
        from bookery.formats.epub import EpubReadError

        with pytest.raises(EpubReadError):
            read_epub_metadata(corrupt_epub)

    def test_nonexistent_file_raises(self, tmp_path: Path) -> None:
        """A nonexistent file raises an EpubReadError."""
        from bookery.formats.epub import EpubReadError

        with pytest.raises(EpubReadError):
            read_epub_metadata(tmp_path / "does_not_exist.epub")

    def test_returns_book_metadata_type(self, sample_epub: Path) -> None:
        """The return type is BookMetadata."""
        meta = read_epub_metadata(sample_epub)
        assert isinstance(meta, BookMetadata)
