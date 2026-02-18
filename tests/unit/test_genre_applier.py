# ABOUTME: Unit tests for the genre applier batch logic.
# ABOUTME: Tests apply_genres() in default, force, dry-run, and edge-case modes.

from pathlib import Path

import pytest

from bookery.core.genre_applier import ApplyResult, apply_genres
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


@pytest.fixture()
def catalog(tmp_path: Path) -> LibraryCatalog:
    """Provide a LibraryCatalog backed by a temporary database."""
    conn = open_library(tmp_path / "applier_test.db")
    return LibraryCatalog(conn)


def _add_book_with_subjects(
    catalog: LibraryCatalog,
    title: str,
    subjects: list[str],
    file_hash: str,
) -> int:
    """Helper to add a book and store subjects."""
    book_id = catalog.add_book(
        BookMetadata(title=title, source_path=Path(f"/{file_hash}.epub")),
        file_hash=file_hash,
    )
    catalog.store_subjects(book_id, subjects)
    return book_id


class TestApplyGenresDefault:
    """Tests for apply_genres() in default mode (no --force)."""

    def test_assigns_genres_to_ungenred_books(self, catalog: LibraryCatalog) -> None:
        """Books with subjects but no genre get genres assigned."""
        _add_book_with_subjects(catalog, "Mystery Novel", ["mystery", "fiction"], "h1")
        result = apply_genres(catalog)
        assert len(result.assigned) == 1
        assert result.assigned[0][2] == "Mystery & Thriller"

    def test_skips_already_genred_books(self, catalog: LibraryCatalog) -> None:
        """Books that already have a genre are skipped in default mode."""
        book_id = _add_book_with_subjects(catalog, "Sci-Fi Book", ["science fiction"], "h2")
        catalog.add_genre(book_id, "Science Fiction", is_primary=True)
        result = apply_genres(catalog)
        assert len(result.assigned) == 0

    def test_records_unmatched_subjects(self, catalog: LibraryCatalog) -> None:
        """Books whose subjects don't map to any genre go in unmatched."""
        _add_book_with_subjects(catalog, "Weird Book", ["xyzzy", "plugh"], "h3")
        result = apply_genres(catalog)
        assert len(result.unmatched) == 1
        assert result.unmatched[0][1] == "Weird Book"
        assert result.unmatched[0][2] == ["xyzzy", "plugh"]

    def test_empty_catalog(self, catalog: LibraryCatalog) -> None:
        """Empty catalog produces zero results."""
        result = apply_genres(catalog)
        assert len(result.assigned) == 0
        assert len(result.unmatched) == 0

    def test_assigns_multiple_genres_from_subjects(self, catalog: LibraryCatalog) -> None:
        """A book with subjects spanning multiple genres gets all of them assigned."""
        book_id = _add_book_with_subjects(
            catalog, "Genre Mashup", ["mystery", "science fiction", "romance"], "h4"
        )
        result = apply_genres(catalog)
        assert len(result.assigned) == 1
        # Verify multiple genres were actually written to DB
        genres = catalog.get_genres_for_book(book_id)
        genre_names = [name for name, _ in genres]
        assert "Mystery & Thriller" in genre_names
        assert "Science Fiction" in genre_names
        assert "Romance" in genre_names

    def test_sets_primary_genre(self, catalog: LibraryCatalog) -> None:
        """The primary genre is set based on the normalizer's vote counting."""
        book_id = _add_book_with_subjects(
            catalog, "Mystery Book", ["mystery", "detective fiction", "fiction"], "h5"
        )
        result = apply_genres(catalog)
        assert len(result.assigned) == 1
        primary = catalog.get_primary_genre(book_id)
        assert primary == "Mystery & Thriller"


class TestApplyGenresForce:
    """Tests for apply_genres() with force=True."""

    def test_re_evaluates_genred_books(self, catalog: LibraryCatalog) -> None:
        """Force mode re-evaluates books that already have genres."""
        book_id = _add_book_with_subjects(
            catalog, "Sci-Fi Book", ["science fiction", "fantasy"], "h6"
        )
        catalog.add_genre(book_id, "Science Fiction", is_primary=True)
        result = apply_genres(catalog, force=True)
        assert len(result.assigned) == 1
        # Should have both genres now
        genres = catalog.get_genres_for_book(book_id)
        genre_names = [name for name, _ in genres]
        assert "Fantasy" in genre_names


class TestApplyGenresDryRun:
    """Tests for apply_genres() with dry_run=True."""

    def test_does_not_write_to_db(self, catalog: LibraryCatalog) -> None:
        """Dry run reports what would happen without modifying the database."""
        book_id = _add_book_with_subjects(
            catalog, "Mystery Novel", ["mystery", "fiction"], "h7"
        )
        result = apply_genres(catalog, dry_run=True)
        assert len(result.assigned) == 1
        # Verify no genres were actually written
        genres = catalog.get_genres_for_book(book_id)
        assert genres == []

    def test_dry_run_with_force(self, catalog: LibraryCatalog) -> None:
        """Dry run + force reports re-evaluation without writing."""
        book_id = _add_book_with_subjects(
            catalog, "Sci-Fi Book", ["science fiction", "fantasy"], "h8"
        )
        catalog.add_genre(book_id, "Science Fiction", is_primary=True)
        result = apply_genres(catalog, dry_run=True, force=True)
        assert len(result.assigned) == 1
        # Only the original genre should remain
        genres = catalog.get_genres_for_book(book_id)
        assert len(genres) == 1


class TestApplyResult:
    """Tests for the ApplyResult dataclass."""

    def test_default_values(self) -> None:
        """ApplyResult initializes with empty/zero defaults."""
        result = ApplyResult()
        assert result.assigned == []
        assert result.skipped_no_match == 0
        assert result.unmatched == []
