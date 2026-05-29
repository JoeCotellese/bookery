# ABOUTME: E2E tests for collection CLI commands via CliRunner.
# ABOUTME: End-to-end workflow tests for collections functionality.

from pathlib import Path

import pytest
from click.testing import CliRunner

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


@pytest.fixture()
def runner() -> CliRunner:
    """Provide a Click CLI test runner."""
    return CliRunner()


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    """Provide a temporary database path."""
    return tmp_path / "e2e_test.db"


class TestCollectionsWorkflow:
    """End-to-end workflow tests for collections."""

    def test_full_collection_workflow(self, runner: CliRunner, db_path: Path) -> None:
        """Test the complete lifecycle of a collection."""
        # Step 1: Create a collection
        result = runner.invoke(
            cli,
            [
                "--db", str(db_path), "collections", "create",
                "Sci-Fi Favorites", "-d", "Best science fiction books"
            ]
        )
        assert result.exit_code == 0
        assert "Created collection" in result.output
        assert "Sci-Fi Favorites" in result.output

        # Step 2: Add some books to the library
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        book_ids = []
        for i in range(5):
            book_id = catalog.add_book(
                BookMetadata(
                    title=f"Sci-Fi Book {i}",
                    authors=[f"Author {i}"],
                    source_path=Path(f"/books/scifi{i}.epub")
                ),
                file_hash=f"hash_{i}",
            )
            book_ids.append(book_id)
        conn.close()

        # Step 3: Add books to the collection
        result = runner.invoke(
            cli,
            ["--db", str(db_path), "collections", "add-books", "1",
             str(book_ids[0]), str(book_ids[1]), str(book_ids[2])]
        )
        assert result.exit_code == 0
        assert "Added 3 book(s)" in result.output

        # Step 4: List collections
        result = runner.invoke(cli, ["--db", str(db_path), "collections", "ls"])
        assert result.exit_code == 0
        assert "Sci-Fi Favorites" in result.output
        assert "3" in result.output  # book count
        assert "Best science fiction books" in result.output

        # Step 5: Show collection details
        result = runner.invoke(cli, ["--db", str(db_path), "collections", "show", "1"])
        assert result.exit_code == 0
        assert "Sci-Fi Favorites" in result.output
        assert "Sci-Fi Book 0" in result.output
        assert "Sci-Fi Book 1" in result.output
        assert "Sci-Fi Book 2" in result.output
        assert "3 book(s)" in result.output

        # Step 6: Remove a book from the collection
        result = runner.invoke(
            cli,
            ["--db", str(db_path), "collections", "remove-books", "1", str(book_ids[1])]
        )
        assert result.exit_code == 0
        assert "Removed 1 book(s)" in result.output

        # Step 7: Show collection again
        result = runner.invoke(cli, ["--db", str(db_path), "collections", "show", "1"])
        assert result.exit_code == 0
        assert "Sci-Fi Book 0" in result.output
        assert "Sci-Fi Book 1" not in result.output  # removed
        assert "2 book(s)" in result.output

        # Step 8: Rename the collection
        result = runner.invoke(
            cli,
            ["--db", str(db_path), "collections", "rename", "1", "Best Sci-Fi"]
        )
        assert result.exit_code == 0
        assert "Renamed collection" in result.output
        assert "Sci-Fi Favorites" in result.output
        assert "Best Sci-Fi" in result.output

        # Step 9: Verify rename
        result = runner.invoke(cli, ["--db", str(db_path), "collections", "show", "1"])
        assert result.exit_code == 0
        assert "Best Sci-Fi" in result.output
        assert "Sci-Fi Favorites" not in result.output

        # Step 10: Delete the collection
        result = runner.invoke(
            cli,
            ["--db", str(db_path), "collections", "rm", "1"],
            input="y\n"
        )
        assert result.exit_code == 0
        assert "Deleted collection" in result.output

        # Step 11: Verify deletion
        result = runner.invoke(cli, ["--db", str(db_path), "collections", "ls"])
        assert result.exit_code == 0
        assert "No collections" in result.output

    def test_multiple_collections_same_book(self, runner: CliRunner, db_path: Path) -> None:
        """A book can belong to multiple collections."""
        # Create two collections
        runner.invoke(cli, ["--db", str(db_path), "collections", "create", "Favorites"])
        runner.invoke(cli, ["--db", str(db_path), "collections", "create", "To Read"])

        # Add a book
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        book_id = catalog.add_book(
            BookMetadata(title="Great Book", source_path=Path("/books/great.epub")),
            file_hash="great_hash",
        )
        conn.close()

        # Add the same book to both collections
        runner.invoke(cli, ["--db", str(db_path), "collections", "add-books", "1", str(book_id)])
        runner.invoke(cli, ["--db", str(db_path), "collections", "add-books", "2", str(book_id)])

        # Verify book is in both collections
        result1 = runner.invoke(cli, ["--db", str(db_path), "collections", "show", "1"])
        result2 = runner.invoke(cli, ["--db", str(db_path), "collections", "show", "2"])

        assert "Great Book" in result1.output
        assert "Great Book" in result2.output

    def test_book_deletion_cascade_from_collection(self, runner: CliRunner, db_path: Path) -> None:
        """Deleting a book removes it from all collections."""
        # Setup
        runner.invoke(cli, ["--db", str(db_path), "collections", "create", "Favorites"])
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        book1 = catalog.add_book(
            BookMetadata(title="Book 1", source_path=Path("/books/1.epub")),
            file_hash="hash1",
        )
        book2 = catalog.add_book(
            BookMetadata(title="Book 2", source_path=Path("/books/2.epub")),
            file_hash="hash2",
        )
        catalog.add_books_to_collection(1, [book1, book2])
        conn.close()

        # Delete book1
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        catalog.delete_book(book1)
        conn.close()

        # Verify only book2 remains in collection
        result = runner.invoke(cli, ["--db", str(db_path), "collections", "show", "1"])
        assert result.exit_code == 0
        assert "Book 1" not in result.output
        assert "Book 2" in result.output
        assert "1 book(s)" in result.output
