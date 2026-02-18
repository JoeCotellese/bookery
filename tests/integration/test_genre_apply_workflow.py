# ABOUTME: Integration tests for the genre apply workflow with a real database.
# ABOUTME: Validates end-to-end genre assignment, idempotency, force, and dry-run.

from pathlib import Path

import pytest

from bookery.core.genre_applier import apply_genres
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


@pytest.fixture()
def catalog(tmp_path: Path) -> LibraryCatalog:
    """Provide a LibraryCatalog backed by a temporary database."""
    conn = open_library(tmp_path / "integration_test.db")
    return LibraryCatalog(conn)


def _populate_catalog(catalog: LibraryCatalog) -> dict[str, int]:
    """Populate the catalog with a mix of books for testing.

    Returns a dict mapping book names to their IDs.
    """
    ids: dict[str, int] = {}

    # Ungenred book with matchable subjects
    ids["mystery"] = catalog.add_book(
        BookMetadata(title="The Big Sleep", source_path=Path("/big_sleep.epub")),
        file_hash="hash_mystery",
    )
    catalog.store_subjects(ids["mystery"], ["mystery", "detective fiction", "noir"])

    # Ungenred book with matchable subjects (multiple genres)
    ids["mashup"] = catalog.add_book(
        BookMetadata(title="Genre Mashup", source_path=Path("/mashup.epub")),
        file_hash="hash_mashup",
    )
    catalog.store_subjects(ids["mashup"], ["science fiction", "romance"])

    # Already genred book
    ids["genred"] = catalog.add_book(
        BookMetadata(title="Dune", source_path=Path("/dune.epub")),
        file_hash="hash_genred",
    )
    catalog.store_subjects(ids["genred"], ["science fiction", "fantasy"])
    catalog.add_genre(ids["genred"], "Science Fiction", is_primary=True)

    # Book with unmatchable subjects
    ids["unmatched"] = catalog.add_book(
        BookMetadata(title="Oddball", source_path=Path("/odd.epub")),
        file_hash="hash_unmatched",
    )
    catalog.store_subjects(ids["unmatched"], ["xyzzy", "plugh"])

    # Book with no subjects
    ids["no_subjects"] = catalog.add_book(
        BookMetadata(title="Blank Slate", source_path=Path("/blank.epub")),
        file_hash="hash_blank",
    )

    return ids


class TestGenreApplyWorkflow:
    """Integration tests for the full genre apply workflow."""

    def test_default_assigns_ungenred_matchable(self, catalog: LibraryCatalog) -> None:
        """Default mode assigns genres only to ungenred books with matchable subjects."""
        ids = _populate_catalog(catalog)

        result = apply_genres(catalog)

        # Mystery and mashup should be assigned
        assert len(result.assigned) == 2
        assigned_ids = {book_id for book_id, _, _ in result.assigned}
        assert ids["mystery"] in assigned_ids
        assert ids["mashup"] in assigned_ids

        # Oddball should be unmatched
        assert len(result.unmatched) == 1
        assert result.unmatched[0][0] == ids["unmatched"]

        # Verify genres in DB
        mystery_genres = catalog.get_genres_for_book(ids["mystery"])
        genre_names = [name for name, _ in mystery_genres]
        assert "Mystery & Thriller" in genre_names

        mystery_primary = catalog.get_primary_genre(ids["mystery"])
        assert mystery_primary == "Mystery & Thriller"

    def test_idempotent_second_run(self, catalog: LibraryCatalog) -> None:
        """Running apply twice assigns nothing on the second run."""
        _populate_catalog(catalog)

        first = apply_genres(catalog)
        assert len(first.assigned) == 2

        second = apply_genres(catalog)
        assert len(second.assigned) == 0

    def test_force_re_evaluates_all(self, catalog: LibraryCatalog) -> None:
        """Force mode re-evaluates all books with subjects, including genred ones."""
        ids = _populate_catalog(catalog)

        result = apply_genres(catalog, force=True)

        # Should include mystery, mashup, AND genred (Dune)
        assigned_ids = {book_id for book_id, _, _ in result.assigned}
        assert ids["mystery"] in assigned_ids
        assert ids["mashup"] in assigned_ids
        assert ids["genred"] in assigned_ids
        assert len(result.assigned) == 3

        # Dune should now also have Fantasy assigned
        dune_genres = catalog.get_genres_for_book(ids["genred"])
        genre_names = [name for name, _ in dune_genres]
        assert "Science Fiction" in genre_names
        assert "Fantasy" in genre_names

    def test_dry_run_no_db_writes(self, catalog: LibraryCatalog) -> None:
        """Dry run reports assignments without writing to the database."""
        ids = _populate_catalog(catalog)

        result = apply_genres(catalog, dry_run=True)

        assert len(result.assigned) == 2

        # Verify nothing was written
        mystery_genres = catalog.get_genres_for_book(ids["mystery"])
        assert mystery_genres == []
        mashup_genres = catalog.get_genres_for_book(ids["mashup"])
        assert mashup_genres == []

    def test_force_after_default_adds_genres_to_already_genred(
        self, catalog: LibraryCatalog
    ) -> None:
        """After a default run, force can add missing genres to previously genred books."""
        ids = _populate_catalog(catalog)

        # Default run: assigns mystery and mashup
        apply_genres(catalog)

        # Force run: should re-evaluate genred book (Dune) and add Fantasy
        result = apply_genres(catalog, force=True)

        # All 3 books with matchable subjects should appear
        assigned_ids = {book_id for book_id, _, _ in result.assigned}
        assert ids["genred"] in assigned_ids

        dune_genres = catalog.get_genres_for_book(ids["genred"])
        genre_names = [name for name, _ in dune_genres]
        assert "Fantasy" in genre_names
