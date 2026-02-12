# ABOUTME: Unit tests for EPUB metadata writing.
# ABOUTME: Tests round-trip: read metadata, modify, write back, verify.

from pathlib import Path

import pytest

from bookery.formats.epub import EpubReadError, read_epub_metadata, write_epub_metadata
from bookery.metadata import BookMetadata


class TestWriteEpubMetadata:
    """Tests for EPUB metadata writing."""

    def test_write_updates_title(self, sample_epub: Path) -> None:
        """Writing new metadata updates the title in the EPUB."""
        original = read_epub_metadata(sample_epub)
        updated = BookMetadata(
            title="Il Nome della Rosa",
            authors=original.authors,
            language=original.language,
            publisher=original.publisher,
            description=original.description,
            identifiers=original.identifiers,
            source_path=original.source_path,
        )
        write_epub_metadata(sample_epub, updated)

        re_read = read_epub_metadata(sample_epub)
        assert re_read.title == "Il Nome della Rosa"

    def test_write_updates_author(self, sample_epub: Path) -> None:
        """Writing new metadata updates the author in the EPUB."""
        original = read_epub_metadata(sample_epub)
        updated = BookMetadata(
            title=original.title,
            authors=["Eco, Umberto"],
            language=original.language,
        )
        write_epub_metadata(sample_epub, updated)

        re_read = read_epub_metadata(sample_epub)
        assert re_read.authors == ["Eco, Umberto"]

    def test_write_updates_language(self, sample_epub: Path) -> None:
        """Writing new metadata updates the language in the EPUB."""
        updated = BookMetadata(title="Test", language="it")
        write_epub_metadata(sample_epub, updated)

        re_read = read_epub_metadata(sample_epub)
        assert re_read.language == "it"

    def test_write_updates_publisher(self, sample_epub: Path) -> None:
        """Writing new metadata updates the publisher in the EPUB."""
        updated = BookMetadata(title="Test", publisher="Bompiani")
        write_epub_metadata(sample_epub, updated)

        re_read = read_epub_metadata(sample_epub)
        assert re_read.publisher == "Bompiani"

    def test_write_updates_description(self, sample_epub: Path) -> None:
        """Writing new metadata updates the description in the EPUB."""
        updated = BookMetadata(title="Test", description="A new description.")
        write_epub_metadata(sample_epub, updated)

        re_read = read_epub_metadata(sample_epub)
        assert re_read.description == "A new description."

    def test_write_preserves_content(self, sample_epub: Path) -> None:
        """Writing metadata does not corrupt the EPUB's content."""
        updated = BookMetadata(title="Updated Title")
        write_epub_metadata(sample_epub, updated)

        # Should still be readable
        meta = read_epub_metadata(sample_epub)
        assert meta.title == "Updated Title"

    def test_write_to_nonexistent_file_raises(self, tmp_path: Path) -> None:
        """Writing to a nonexistent file raises an error."""
        meta = BookMetadata(title="Ghost")
        with pytest.raises(EpubReadError):
            write_epub_metadata(tmp_path / "ghost.epub", meta)

    def test_write_to_corrupt_file_raises(self, corrupt_epub: Path) -> None:
        """Writing to a corrupt file raises an error."""
        meta = BookMetadata(title="Fix")
        with pytest.raises(EpubReadError):
            write_epub_metadata(corrupt_epub, meta)

    def test_round_trip_preserves_unmodified_fields(self, sample_epub: Path) -> None:
        """Fields not in the update are preserved from the original EPUB."""
        original = read_epub_metadata(sample_epub)

        # Only update the title, keep everything else
        updated = BookMetadata(
            title="New Title",
            authors=original.authors,
            language=original.language,
            publisher=original.publisher,
            description=original.description,
            identifiers=original.identifiers,
        )
        write_epub_metadata(sample_epub, updated)

        re_read = read_epub_metadata(sample_epub)
        assert re_read.title == "New Title"
        assert re_read.authors == ["Umberto Eco"]
        assert re_read.publisher == "Harcourt"
        assert re_read.description == "A mystery set in a medieval monastery."
