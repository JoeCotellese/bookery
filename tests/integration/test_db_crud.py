# ABOUTME: Integration tests for LibraryCatalog CRUD with real database operations.
# ABOUTME: Validates multi-book workflows and round-trip data integrity.

from pathlib import Path

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


class TestCatalogIntegration:
    """Integration tests for catalog operations across multiple books."""

    def test_add_and_list_multiple_books(self, tmp_path: Path) -> None:
        """Add 3 books, list returns 3 with correct data."""
        conn = open_library(tmp_path / "multi.db")
        catalog = LibraryCatalog(conn)

        titles = ["Book Alpha", "Book Beta", "Book Gamma"]
        for i, title in enumerate(titles):
            catalog.add_book(
                BookMetadata(title=title, source_path=Path(f"/books/{i}.epub")),
                file_hash=f"hash_{i}",
            )

        results = catalog.list_all()
        assert len(results) == 3
        result_titles = {r.metadata.title for r in results}
        assert result_titles == set(titles)
        conn.close()

    def test_add_update_verify(self, tmp_path: Path) -> None:
        """Add a book, update its author, verify the change persists."""
        conn = open_library(tmp_path / "update.db")
        catalog = LibraryCatalog(conn)

        book_id = catalog.add_book(
            BookMetadata(
                title="Foucault's Pendulum",
                authors=["U. Eco"],
                source_path=Path("/books/fp.epub"),
            ),
            file_hash="fp_hash",
        )

        catalog.update_book(book_id, authors=["Umberto Eco"])

        record = catalog.get_by_id(book_id)
        assert record is not None
        assert record.metadata.authors == ["Umberto Eco"]
        conn.close()

    def test_delete_then_reuse_hash(self, tmp_path: Path) -> None:
        """After deleting a book, the same hash can be used for a new book."""
        conn = open_library(tmp_path / "reuse.db")
        catalog = LibraryCatalog(conn)

        book_id = catalog.add_book(
            BookMetadata(title="Old Book", source_path=Path("/old.epub")),
            file_hash="reusable_hash",
        )
        catalog.delete_book(book_id)

        new_id = catalog.add_book(
            BookMetadata(title="New Book", source_path=Path("/new.epub")),
            file_hash="reusable_hash",
        )
        record = catalog.get_by_id(new_id)
        assert record is not None
        assert record.metadata.title == "New Book"
        conn.close()
