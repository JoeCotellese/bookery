# ABOUTME: Unit tests for tag CRUD operations on LibraryCatalog.
# ABOUTME: Validates add, remove, list, and query methods for the tagging system.

from pathlib import Path

import pytest

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


@pytest.fixture()
def catalog(tmp_path: Path) -> LibraryCatalog:
    """Provide a LibraryCatalog backed by a temporary database."""
    conn = open_library(tmp_path / "tags_test.db")
    return LibraryCatalog(conn)


@pytest.fixture()
def book_id(catalog: LibraryCatalog) -> int:
    """Add a sample book and return its ID."""
    return catalog.add_book(
        BookMetadata(title="The Name of the Rose", source_path=Path("/books/rose.epub")),
        file_hash="rose_hash",
    )


class TestAddTag:
    """Tests for LibraryCatalog.add_tag()."""

    def test_add_tag_to_book(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Adding a tag associates it with the book."""
        catalog.add_tag(book_id, "fiction")
        tags = catalog.get_tags_for_book(book_id)
        assert tags == ["fiction"]

    def test_add_multiple_tags(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Multiple tags can be added to a single book."""
        catalog.add_tag(book_id, "fiction")
        catalog.add_tag(book_id, "mystery")
        tags = catalog.get_tags_for_book(book_id)
        assert tags == ["fiction", "mystery"]

    def test_add_tag_is_idempotent(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Adding the same tag twice does not raise or duplicate."""
        catalog.add_tag(book_id, "fiction")
        catalog.add_tag(book_id, "fiction")
        tags = catalog.get_tags_for_book(book_id)
        assert tags == ["fiction"]

    def test_add_tag_case_insensitive(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Tags with different cases are treated as the same tag."""
        catalog.add_tag(book_id, "Fiction")
        catalog.add_tag(book_id, "fiction")
        tags = catalog.get_tags_for_book(book_id)
        assert len(tags) == 1

    def test_add_tag_invalid_book_raises(self, catalog: LibraryCatalog) -> None:
        """Adding a tag to a nonexistent book raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            catalog.add_tag(9999, "fiction")


class TestRemoveTag:
    """Tests for LibraryCatalog.remove_tag()."""

    def test_remove_existing_tag(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Removing an existing tag disassociates it from the book."""
        catalog.add_tag(book_id, "fiction")
        catalog.remove_tag(book_id, "fiction")
        tags = catalog.get_tags_for_book(book_id)
        assert tags == []

    def test_remove_nonexistent_tag_raises(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Removing a tag that doesn't exist raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            catalog.remove_tag(book_id, "nonexistent")

    def test_remove_unassociated_tag_raises(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Removing a tag not associated with the book raises ValueError."""
        catalog.add_tag(book_id, "fiction")

        book_id_2 = catalog.add_book(
            BookMetadata(title="Book Two", source_path=Path("/books/two.epub")),
            file_hash="two_hash",
        )
        with pytest.raises(ValueError, match="not tagged"):
            catalog.remove_tag(book_id_2, "fiction")


class TestGetTagsForBook:
    """Tests for LibraryCatalog.get_tags_for_book()."""

    def test_no_tags_returns_empty_list(self, catalog: LibraryCatalog, book_id: int) -> None:
        """A book with no tags returns an empty list."""
        tags = catalog.get_tags_for_book(book_id)
        assert tags == []

    def test_tags_sorted_alphabetically(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Tags are returned in alphabetical order."""
        catalog.add_tag(book_id, "mystery")
        catalog.add_tag(book_id, "fiction")
        catalog.add_tag(book_id, "award-winner")
        tags = catalog.get_tags_for_book(book_id)
        assert tags == ["award-winner", "fiction", "mystery"]


class TestListTags:
    """Tests for LibraryCatalog.list_tags()."""

    def test_empty_library_no_tags(self, catalog: LibraryCatalog) -> None:
        """An empty library returns no tags."""
        assert catalog.list_tags() == []

    def test_list_tags_with_counts(self, catalog: LibraryCatalog) -> None:
        """list_tags returns tag names with book counts."""
        id1 = catalog.add_book(
            BookMetadata(title="Book A", source_path=Path("/a.epub")),
            file_hash="hash_a",
        )
        id2 = catalog.add_book(
            BookMetadata(title="Book B", source_path=Path("/b.epub")),
            file_hash="hash_b",
        )
        catalog.add_tag(id1, "fiction")
        catalog.add_tag(id2, "fiction")
        catalog.add_tag(id1, "mystery")

        result = catalog.list_tags()
        assert ("fiction", 2) in result
        assert ("mystery", 1) in result

    def test_list_tags_alphabetical(self, catalog: LibraryCatalog) -> None:
        """Tags are returned in alphabetical order."""
        book_id = catalog.add_book(
            BookMetadata(title="Book", source_path=Path("/b.epub")),
            file_hash="hash_b",
        )
        catalog.add_tag(book_id, "zebra")
        catalog.add_tag(book_id, "alpha")
        result = catalog.list_tags()
        names = [name for name, _ in result]
        assert names == ["alpha", "zebra"]


class TestGetBooksByTag:
    """Tests for LibraryCatalog.get_books_by_tag()."""

    def test_get_books_by_tag(self, catalog: LibraryCatalog) -> None:
        """Returns all books with the given tag."""
        id1 = catalog.add_book(
            BookMetadata(title="Book A", source_path=Path("/a.epub")),
            file_hash="hash_a",
        )
        id2 = catalog.add_book(
            BookMetadata(title="Book B", source_path=Path("/b.epub")),
            file_hash="hash_b",
        )
        catalog.add_tag(id1, "fiction")
        catalog.add_tag(id2, "fiction")

        results = catalog.get_books_by_tag("fiction")
        assert len(results) == 2
        titles = {r.metadata.title for r in results}
        assert titles == {"Book A", "Book B"}

    def test_get_books_by_tag_case_insensitive(self, catalog: LibraryCatalog) -> None:
        """Tag lookup is case-insensitive."""
        book_id = catalog.add_book(
            BookMetadata(title="Book", source_path=Path("/b.epub")),
            file_hash="hash_b",
        )
        catalog.add_tag(book_id, "Fiction")
        results = catalog.get_books_by_tag("fiction")
        assert len(results) == 1

    def test_get_books_by_nonexistent_tag_raises(self, catalog: LibraryCatalog) -> None:
        """Querying a tag that doesn't exist raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            catalog.get_books_by_tag("nonexistent")
