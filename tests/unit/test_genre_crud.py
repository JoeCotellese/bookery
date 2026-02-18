# ABOUTME: Unit tests for genre CRUD operations on LibraryCatalog.
# ABOUTME: Validates add, remove, set primary, list, and query methods for genres.

from pathlib import Path

import pytest

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


@pytest.fixture()
def catalog(tmp_path: Path) -> LibraryCatalog:
    """Provide a LibraryCatalog backed by a temporary database."""
    conn = open_library(tmp_path / "genre_test.db")
    return LibraryCatalog(conn)


@pytest.fixture()
def book_id(catalog: LibraryCatalog) -> int:
    """Add a sample book and return its ID."""
    return catalog.add_book(
        BookMetadata(title="The Name of the Rose", source_path=Path("/books/rose.epub")),
        file_hash="rose_hash",
    )


class TestAddGenre:
    """Tests for LibraryCatalog.add_genre()."""

    def test_add_genre_to_book(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Adding a genre associates it with the book."""
        catalog.add_genre(book_id, "Literary Fiction")
        genres = catalog.get_genres_for_book(book_id)
        assert ("Literary Fiction", False) in genres

    def test_add_invalid_genre_raises(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Adding a non-canonical genre raises ValueError."""
        with pytest.raises(ValueError, match="not a canonical genre"):
            catalog.add_genre(book_id, "Made Up Genre")

    def test_add_genre_is_idempotent(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Adding the same genre twice does not duplicate."""
        catalog.add_genre(book_id, "Literary Fiction")
        catalog.add_genre(book_id, "Literary Fiction")
        genres = catalog.get_genres_for_book(book_id)
        literary_count = sum(1 for name, _ in genres if name == "Literary Fiction")
        assert literary_count == 1

    def test_add_genre_invalid_book_raises(self, catalog: LibraryCatalog) -> None:
        """Adding a genre to a nonexistent book raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            catalog.add_genre(9999, "Literary Fiction")

    def test_add_genre_with_primary(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Adding a genre with is_primary=True marks it as primary."""
        catalog.add_genre(book_id, "Literary Fiction", is_primary=True)
        genres = catalog.get_genres_for_book(book_id)
        assert ("Literary Fiction", True) in genres


class TestRemoveGenre:
    """Tests for LibraryCatalog.remove_genre()."""

    def test_remove_existing_genre(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Removing an existing genre disassociates it from the book."""
        catalog.add_genre(book_id, "Literary Fiction")
        catalog.remove_genre(book_id, "Literary Fiction")
        genres = catalog.get_genres_for_book(book_id)
        assert genres == []

    def test_remove_nonexistent_genre_raises(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Removing a genre not assigned to the book raises ValueError."""
        with pytest.raises(ValueError, match="not assigned"):
            catalog.remove_genre(book_id, "Literary Fiction")


class TestSetPrimaryGenre:
    """Tests for LibraryCatalog.set_primary_genre()."""

    def test_sets_primary(self, catalog: LibraryCatalog, book_id: int) -> None:
        """set_primary_genre marks a genre as primary."""
        catalog.add_genre(book_id, "Literary Fiction")
        catalog.add_genre(book_id, "Mystery & Thriller")
        catalog.set_primary_genre(book_id, "Mystery & Thriller")
        assert catalog.get_primary_genre(book_id) == "Mystery & Thriller"

    def test_clears_previous_primary(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Setting a new primary clears the previous one."""
        catalog.add_genre(book_id, "Literary Fiction", is_primary=True)
        catalog.add_genre(book_id, "Mystery & Thriller")
        catalog.set_primary_genre(book_id, "Mystery & Thriller")
        assert catalog.get_primary_genre(book_id) == "Mystery & Thriller"
        # Only one primary
        genres = catalog.get_genres_for_book(book_id)
        primaries = [name for name, is_primary in genres if is_primary]
        assert primaries == ["Mystery & Thriller"]


class TestGetGenresForBook:
    """Tests for LibraryCatalog.get_genres_for_book()."""

    def test_no_genres_returns_empty_list(self, catalog: LibraryCatalog, book_id: int) -> None:
        """A book with no genres returns an empty list."""
        assert catalog.get_genres_for_book(book_id) == []

    def test_genres_sorted_alphabetically(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Genres are returned in alphabetical order."""
        catalog.add_genre(book_id, "Science Fiction")
        catalog.add_genre(book_id, "Fantasy")
        catalog.add_genre(book_id, "Horror")
        genres = [name for name, _ in catalog.get_genres_for_book(book_id)]
        assert genres == ["Fantasy", "Horror", "Science Fiction"]


class TestGetPrimaryGenre:
    """Tests for LibraryCatalog.get_primary_genre()."""

    def test_returns_none_when_no_genres(self, catalog: LibraryCatalog, book_id: int) -> None:
        """No genres returns None."""
        assert catalog.get_primary_genre(book_id) is None

    def test_returns_none_when_no_primary(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Genres without primary returns None."""
        catalog.add_genre(book_id, "Literary Fiction")
        assert catalog.get_primary_genre(book_id) is None

    def test_returns_primary(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Returns the primary genre name."""
        catalog.add_genre(book_id, "Literary Fiction", is_primary=True)
        assert catalog.get_primary_genre(book_id) == "Literary Fiction"


class TestListGenres:
    """Tests for LibraryCatalog.list_genres()."""

    def test_returns_all_14_genres(self, catalog: LibraryCatalog) -> None:
        """list_genres returns all 14 canonical genres with counts."""
        result = catalog.list_genres()
        assert len(result) == 14

    def test_counts_are_zero_initially(self, catalog: LibraryCatalog) -> None:
        """All genres start with 0 book count."""
        result = catalog.list_genres()
        for _, count in result:
            assert count == 0

    def test_counts_reflect_assignments(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Assigned genres have correct counts."""
        catalog.add_genre(book_id, "Literary Fiction")
        result = dict(catalog.list_genres())
        assert result["Literary Fiction"] == 1


class TestGetBooksByGenre:
    """Tests for LibraryCatalog.get_books_by_genre()."""

    def test_returns_matching_books(self, catalog: LibraryCatalog) -> None:
        """Returns books assigned to the genre."""
        id1 = catalog.add_book(
            BookMetadata(title="Book A", source_path=Path("/a.epub")),
            file_hash="hash_a",
        )
        id2 = catalog.add_book(
            BookMetadata(title="Book B", source_path=Path("/b.epub")),
            file_hash="hash_b",
        )
        catalog.add_genre(id1, "Literary Fiction")
        catalog.add_genre(id2, "Literary Fiction")
        results = catalog.get_books_by_genre("Literary Fiction")
        assert len(results) == 2

    def test_invalid_genre_raises(self, catalog: LibraryCatalog) -> None:
        """Querying a non-canonical genre raises ValueError."""
        with pytest.raises(ValueError, match="not a canonical genre"):
            catalog.get_books_by_genre("Made Up Genre")


class TestStoreSubjects:
    """Tests for LibraryCatalog.store_subjects()."""

    def test_stores_subjects(self, catalog: LibraryCatalog, book_id: int) -> None:
        """store_subjects updates the subjects JSON column."""
        catalog.store_subjects(book_id, ["Fiction", "Mystery"])
        record = catalog.get_by_id(book_id)
        assert record is not None
        assert record.metadata.subjects == ["Fiction", "Mystery"]

    def test_stores_empty_subjects(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Empty subjects list can be stored."""
        catalog.store_subjects(book_id, [])
        record = catalog.get_by_id(book_id)
        assert record is not None
        assert record.metadata.subjects == []


class TestGetUnmatchedSubjects:
    """Tests for LibraryCatalog.get_unmatched_subjects()."""

    def test_books_with_subjects_but_no_genre(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Books with subjects but no genre appear in unmatched."""
        catalog.store_subjects(book_id, ["Fiction", "Unknown Subject"])
        unmatched = catalog.get_unmatched_subjects()
        assert len(unmatched) == 1
        assert unmatched[0][0] == book_id
        assert unmatched[0][1] == "The Name of the Rose"
        assert unmatched[0][2] == ["Fiction", "Unknown Subject"]

    def test_books_with_genre_not_in_unmatched(
        self, catalog: LibraryCatalog, book_id: int
    ) -> None:
        """Books with genres assigned are not unmatched."""
        catalog.store_subjects(book_id, ["Fiction"])
        catalog.add_genre(book_id, "Literary Fiction")
        unmatched = catalog.get_unmatched_subjects()
        assert len(unmatched) == 0

    def test_books_without_subjects_not_in_unmatched(self, catalog: LibraryCatalog) -> None:
        """Books without subjects are not in unmatched."""
        catalog.add_book(
            BookMetadata(title="No Subjects", source_path=Path("/ns.epub")),
            file_hash="ns_hash",
        )
        unmatched = catalog.get_unmatched_subjects()
        assert len(unmatched) == 0


class TestGetBooksWithSubjects:
    """Tests for LibraryCatalog.get_books_with_subjects()."""

    def test_returns_books_with_subjects(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Books with subjects are returned regardless of genre status."""
        catalog.store_subjects(book_id, ["Fiction", "Mystery"])
        catalog.add_genre(book_id, "Literary Fiction")
        results = catalog.get_books_with_subjects()
        assert len(results) == 1
        assert results[0][0] == book_id
        assert results[0][1] == "The Name of the Rose"
        assert results[0][2] == ["Fiction", "Mystery"]

    def test_excludes_books_without_subjects(self, catalog: LibraryCatalog) -> None:
        """Books without subjects are excluded."""
        catalog.add_book(
            BookMetadata(title="No Subjects", source_path=Path("/ns.epub")),
            file_hash="ns_hash",
        )
        results = catalog.get_books_with_subjects()
        assert len(results) == 0

    def test_excludes_books_with_empty_subjects(
        self, catalog: LibraryCatalog, book_id: int
    ) -> None:
        """Books with empty subjects list are excluded."""
        catalog.store_subjects(book_id, [])
        results = catalog.get_books_with_subjects()
        assert len(results) == 0

    def test_includes_genred_and_ungenred(self, catalog: LibraryCatalog) -> None:
        """Both genred and ungenred books with subjects are returned."""
        id1 = catalog.add_book(
            BookMetadata(title="Genred Book", source_path=Path("/g.epub")),
            file_hash="hash_g",
        )
        id2 = catalog.add_book(
            BookMetadata(title="Ungenred Book", source_path=Path("/u.epub")),
            file_hash="hash_u",
        )
        catalog.store_subjects(id1, ["Fiction"])
        catalog.store_subjects(id2, ["Mystery"])
        catalog.add_genre(id1, "Literary Fiction")
        results = catalog.get_books_with_subjects()
        assert len(results) == 2
