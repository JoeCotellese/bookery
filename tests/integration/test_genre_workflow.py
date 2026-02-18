# ABOUTME: Integration tests for the genre CRUD workflow.
# ABOUTME: Validates genre assignment, query, and primary genre operations end-to-end.

from pathlib import Path

import pytest

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


@pytest.fixture()
def catalog(tmp_path: Path) -> LibraryCatalog:
    """Provide a LibraryCatalog backed by a temporary database."""
    conn = open_library(tmp_path / "genre_integration.db")
    return LibraryCatalog(conn)


class TestGenreWorkflow:
    """Integration tests for genre CRUD operations."""

    def test_full_genre_crud_cycle(self, catalog: LibraryCatalog) -> None:
        """Add genres, set primary, query, remove — full cycle."""
        book_id = catalog.add_book(
            BookMetadata(title="Dune", source_path=Path("/dune.epub")),
            file_hash="dune_hash",
        )

        # Assign genres
        catalog.add_genre(book_id, "Science Fiction")
        catalog.add_genre(book_id, "Literary Fiction")

        # Verify both assigned
        genres = catalog.get_genres_for_book(book_id)
        names = [name for name, _ in genres]
        assert "Science Fiction" in names
        assert "Literary Fiction" in names

        # Set primary
        catalog.set_primary_genre(book_id, "Science Fiction")
        assert catalog.get_primary_genre(book_id) == "Science Fiction"

        # Query by genre
        books = catalog.get_books_by_genre("Science Fiction")
        assert len(books) == 1
        assert books[0].metadata.title == "Dune"

        # List genres shows correct counts
        genre_dict = dict(catalog.list_genres())
        assert genre_dict["Science Fiction"] == 1
        assert genre_dict["Literary Fiction"] == 1
        assert genre_dict["Fantasy"] == 0

        # Remove a genre
        catalog.remove_genre(book_id, "Literary Fiction")
        genres = catalog.get_genres_for_book(book_id)
        names = [name for name, _ in genres]
        assert "Literary Fiction" not in names
        assert "Science Fiction" in names

    def test_subjects_and_unmatched_workflow(self, catalog: LibraryCatalog) -> None:
        """Store subjects, check unmatched, then assign genre to resolve."""
        book_id = catalog.add_book(
            BookMetadata(title="Obscure Book", source_path=Path("/obscure.epub")),
            file_hash="obscure_hash",
        )

        # Store subjects with no genre match
        catalog.store_subjects(book_id, ["underwater philosophy", "deep thoughts"])

        # Book should appear in unmatched
        unmatched = catalog.get_unmatched_subjects()
        assert len(unmatched) == 1
        assert unmatched[0][1] == "Obscure Book"

        # Manually assign a genre
        catalog.add_genre(book_id, "Philosophy & Religion")

        # Now should be resolved
        unmatched = catalog.get_unmatched_subjects()
        assert len(unmatched) == 0


class TestImportGenreIntegration:
    """Integration test for import with genre auto-assignment."""

    def test_import_assigns_genres_from_subjects(
        self, catalog: LibraryCatalog, sample_epub: Path
    ) -> None:
        """Import pipeline auto-assigns genres from subject metadata."""
        from bookery.core.importer import MatchResult, import_books
        from bookery.metadata.types import BookMetadata

        def match_fn(meta: BookMetadata, path: Path) -> MatchResult:
            meta.subjects = ["mystery", "detective fiction", "fiction"]
            return MatchResult(metadata=meta)

        result = import_books([sample_epub], catalog, match_fn=match_fn)
        assert result.added == 1

        # Genres auto-assigned
        genres = catalog.get_genres_for_book(1)
        genre_names = [name for name, _ in genres]
        assert "Mystery & Thriller" in genre_names
        assert "Literary Fiction" in genre_names

        # Primary genre set (Mystery & Thriller has 2 votes, Literary Fiction has 1)
        primary = catalog.get_primary_genre(1)
        assert primary == "Mystery & Thriller"

        # Subjects stored
        record = catalog.get_by_id(1)
        assert record is not None
        assert "mystery" in record.metadata.subjects
