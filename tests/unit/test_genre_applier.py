# ABOUTME: Unit tests for the genre applier batch logic.
# ABOUTME: Tests apply_genres() in default, force, dry-run, and edge-case modes.

from pathlib import Path

import pytest

from bookery.core.genre_applier import (
    PRIMARY_GENRE_FIELD,
    ApplyResult,
    apply_genres,
    auto_apply_for_book,
    collect_unmatched_subject_frequencies,
)
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


class TestAutoApplyForBook:
    """Tests for auto_apply_for_book() (single-book genre hook)."""

    def test_assigns_primary_from_subjects(self, catalog: LibraryCatalog) -> None:
        book_id = _add_book_with_subjects(
            catalog, "Mystery Novel", ["mystery", "thriller"], "h1"
        )
        primary = auto_apply_for_book(catalog, book_id, ["mystery", "thriller"])
        assert primary == "Mystery & Thriller"
        assert catalog.get_primary_genre(book_id) == "Mystery & Thriller"
        prov = catalog.get_provenance(book_id)
        assert PRIMARY_GENRE_FIELD in prov
        assert prov[PRIMARY_GENRE_FIELD].source == "genres"

    def test_locked_primary_genre_is_preserved(self, catalog: LibraryCatalog) -> None:
        book_id = _add_book_with_subjects(
            catalog, "Mystery Novel", ["fantasy"], "h2"
        )
        catalog.add_genre(book_id, "Fantasy", is_primary=True)
        catalog.set_field_lock(book_id, PRIMARY_GENRE_FIELD, True)
        # Try to auto-apply with subjects that would pick a different primary.
        primary = auto_apply_for_book(catalog, book_id, ["mystery", "thriller"])
        assert catalog.get_primary_genre(book_id) == "Fantasy"
        # Returned value reflects preserved state
        assert primary == "Fantasy"

    def test_unmatched_subjects_leave_book_unmapped(
        self, catalog: LibraryCatalog
    ) -> None:
        book_id = _add_book_with_subjects(
            catalog, "Oddity", ["quantum chromodynamics"], "h3"
        )
        primary = auto_apply_for_book(
            catalog, book_id, ["quantum chromodynamics"]
        )
        assert primary is None
        assert catalog.get_primary_genre(book_id) is None


class TestUpdateBookHook:
    """Confirm catalog.update_book triggers auto_apply_for_book via hook."""

    def test_update_book_with_subjects_triggers_auto_assignment(
        self, catalog: LibraryCatalog
    ) -> None:
        book_id = catalog.add_book(
            BookMetadata(title="T", source_path=Path("/t.epub")),
            file_hash="h4",
        )
        catalog.update_book(
            book_id,
            source="openlibrary",
            subjects=["science fiction", "space opera"],
        )
        assert catalog.get_primary_genre(book_id) == "Science Fiction"

    def test_update_book_without_subjects_does_not_touch_genres(
        self, catalog: LibraryCatalog
    ) -> None:
        book_id = _add_book_with_subjects(catalog, "T", ["fantasy"], "h5")
        catalog.add_genre(book_id, "Fantasy", is_primary=True)
        catalog.update_book(book_id, source="user", publisher="Ace")
        assert catalog.get_primary_genre(book_id) == "Fantasy"


class TestCollectUnmatchedSubjectFrequencies:
    def test_counts_only_unmapped_subjects(self, catalog: LibraryCatalog) -> None:
        _add_book_with_subjects(
            catalog, "A", ["widgetology", "science fiction"], "h6"
        )
        _add_book_with_subjects(catalog, "B", ["widgetology"], "h7")
        freq = collect_unmatched_subject_frequencies(catalog)
        assert ("widgetology", 2) in freq
        assert all(sub != "science fiction" for sub, _ in freq)


class TestApplyResult:
    """Tests for the ApplyResult dataclass."""

    def test_default_values(self) -> None:
        """ApplyResult initializes with empty/zero defaults."""
        result = ApplyResult()
        assert result.assigned == []
        assert result.unmatched == []
