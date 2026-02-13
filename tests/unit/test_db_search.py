# ABOUTME: Unit tests for full-text search via FTS5 in LibraryCatalog.
# ABOUTME: Validates search by title, author, description, ranking, and updates.

from pathlib import Path

import pytest

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


@pytest.fixture()
def catalog(tmp_path: Path) -> LibraryCatalog:
    """Provide a catalog pre-loaded with sample books."""
    conn = open_library(tmp_path / "search.db")
    cat = LibraryCatalog(conn)

    cat.add_book(
        BookMetadata(
            title="The Name of the Rose",
            authors=["Umberto Eco"],
            description="A mystery set in a medieval Italian monastery.",
            source_path=Path("/books/rose.epub"),
        ),
        file_hash="hash_rose",
    )
    cat.add_book(
        BookMetadata(
            title="Foucault's Pendulum",
            authors=["Umberto Eco"],
            description="A conspiracy thriller involving Templars.",
            series="Eco Novels",
            source_path=Path("/books/fp.epub"),
        ),
        file_hash="hash_fp",
    )
    cat.add_book(
        BookMetadata(
            title="The Alexandria Link",
            authors=["Steve Berry"],
            description="Cotton Malone races to find the lost Library of Alexandria.",
            series="Cotton Malone",
            source_path=Path("/books/al.epub"),
        ),
        file_hash="hash_al",
    )
    return cat


class TestSearch:
    """Tests for LibraryCatalog.search."""

    def test_search_by_title(self, catalog: LibraryCatalog) -> None:
        """Search by title keyword finds the right book."""
        results = catalog.search("Rose")
        assert len(results) >= 1
        assert any(r.metadata.title == "The Name of the Rose" for r in results)

    def test_search_by_author(self, catalog: LibraryCatalog) -> None:
        """Search by author name finds their books."""
        results = catalog.search("Eco")
        assert len(results) >= 2
        titles = {r.metadata.title for r in results}
        assert "The Name of the Rose" in titles
        assert "Foucault's Pendulum" in titles

    def test_search_by_description(self, catalog: LibraryCatalog) -> None:
        """Search matches against description text."""
        results = catalog.search("monastery")
        assert len(results) >= 1
        assert results[0].metadata.title == "The Name of the Rose"

    def test_search_by_series(self, catalog: LibraryCatalog) -> None:
        """Search matches against series name."""
        results = catalog.search("Cotton Malone")
        assert len(results) >= 1
        assert results[0].metadata.title == "The Alexandria Link"

    def test_search_returns_empty_for_no_match(self, catalog: LibraryCatalog) -> None:
        """Search returns empty list when nothing matches."""
        results = catalog.search("zzz_nonexistent_xyz")
        assert results == []

    def test_search_after_update(self, catalog: LibraryCatalog) -> None:
        """After updating a title, old title no longer matches and new title does."""
        results = catalog.search("Rose")
        assert len(results) >= 1
        book_id = results[0].id

        catalog.update_book(book_id, title="Il Nome della Rosa")

        # Old title should not match
        old_results = catalog.search("Rose")
        old_titles = {r.metadata.title for r in old_results}
        assert "The Name of the Rose" not in old_titles

        # New title should match
        new_results = catalog.search("Rosa")
        assert len(new_results) >= 1
        assert any(r.metadata.title == "Il Nome della Rosa" for r in new_results)

    def test_search_after_delete(self, catalog: LibraryCatalog) -> None:
        """Deleted books no longer appear in search results."""
        results = catalog.search("Alexandria")
        assert len(results) >= 1
        book_id = results[0].id

        catalog.delete_book(book_id)

        results_after = catalog.search("Alexandria")
        assert len(results_after) == 0
