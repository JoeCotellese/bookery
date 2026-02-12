# ABOUTME: Unit tests for the BookMetadata dataclass.
# ABOUTME: Validates construction, properties, and edge cases.

from pathlib import Path

from bookery.metadata import BookMetadata


class TestBookMetadata:
    """Tests for BookMetadata dataclass."""

    def test_minimal_construction(self) -> None:
        """A BookMetadata can be created with just a title."""
        meta = BookMetadata(title="Test Book")
        assert meta.title == "Test Book"
        assert meta.authors == []
        assert meta.author == ""
        assert meta.language is None
        assert meta.publisher is None
        assert meta.isbn is None
        assert meta.description is None
        assert meta.series is None
        assert meta.series_index is None
        assert meta.identifiers == {}
        assert meta.cover_image is None
        assert meta.source_path is None

    def test_full_construction(self) -> None:
        """A BookMetadata can be created with all fields populated."""
        meta = BookMetadata(
            title="The Name of the Rose",
            authors=["Umberto Eco"],
            author_sort="Eco, Umberto",
            language="en",
            publisher="Harcourt",
            isbn="978-0-123456-47-2",
            description="A mystery in a monastery.",
            series="None",
            series_index=1.0,
            identifiers={"isbn": "978-0-123456-47-2", "openlibrary": "OL123"},
            cover_image=b"\x89PNG",
            source_path=Path("/books/rose.epub"),
        )
        assert meta.title == "The Name of the Rose"
        assert meta.author == "Umberto Eco"
        assert meta.publisher == "Harcourt"
        assert meta.has_cover is True

    def test_multiple_authors(self) -> None:
        """The author property joins multiple authors with commas."""
        meta = BookMetadata(
            title="Good Omens",
            authors=["Terry Pratchett", "Neil Gaiman"],
        )
        assert meta.author == "Terry Pratchett, Neil Gaiman"

    def test_has_cover_false_when_none(self) -> None:
        """has_cover is False when cover_image is None."""
        meta = BookMetadata(title="No Cover")
        assert meta.has_cover is False

    def test_has_cover_false_when_empty_bytes(self) -> None:
        """has_cover is False when cover_image is empty bytes."""
        meta = BookMetadata(title="Empty Cover", cover_image=b"")
        assert meta.has_cover is False

    def test_has_cover_true_when_populated(self) -> None:
        """has_cover is True when cover_image has data."""
        meta = BookMetadata(title="With Cover", cover_image=b"\x89PNG\r\n")
        assert meta.has_cover is True
