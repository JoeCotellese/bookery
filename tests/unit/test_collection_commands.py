# ABOUTME: Unit tests for collection CLI commands.
# ABOUTME: Validates create, add-books, remove-books, ls, show, rm, rename subcommands.

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
def catalog(tmp_path: Path) -> LibraryCatalog:
    """Provide a LibraryCatalog backed by a temporary database."""
    conn = open_library(tmp_path / "cli_test.db")
    return LibraryCatalog(conn)


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    """Provide a temporary database path."""
    return tmp_path / "cli_test.db"


class TestCollectionsCreate:
    """Tests for `collections create` command."""

    def test_create_collection_success(self, runner: CliRunner, db_path: Path) -> None:
        """Creating a collection succeeds with valid input."""
        result = runner.invoke(cli, ["--db", str(db_path), "collections", "create", "Favorites"])
        assert result.exit_code == 0
        assert "Created collection" in result.output
        assert "Favorites" in result.output

    def test_create_collection_with_description(self, runner: CliRunner, db_path: Path) -> None:
        """Creating a collection with description stores it."""
        result = runner.invoke(
            cli,
            ["--db", str(db_path), "collections", "create", "Favorites", "-d", "My favorite books"]
        )
        assert result.exit_code == 0

        # Verify via show command
        result2 = runner.invoke(cli, ["--db", str(db_path), "collections", "show", "1"])
        assert result2.exit_code == 0
        assert "My favorite books" in result2.output

    def test_create_duplicate_shows_error(self, runner: CliRunner, db_path: Path) -> None:
        """Creating a duplicate collection shows error."""
        runner.invoke(cli, ["--db", str(db_path), "collections", "create", "Favorites"])
        result = runner.invoke(cli, ["--db", str(db_path), "collections", "create", "Favorites"])
        assert result.exit_code == 1
        assert "Failed to create collection" in result.output


class TestCollectionsAddBooks:
    """Tests for `collections add-books` command."""

    def test_add_books_success(self, runner: CliRunner, db_path: Path) -> None:
        """Adding books to a collection succeeds."""
        # Create collection
        runner.invoke(cli, ["--db", str(db_path), "collections", "create", "Favorites"])

        # Add books
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        for i in range(3):
            catalog.add_book(
                BookMetadata(title=f"Book {i}", source_path=Path(f"/books/{i}.epub")),
                file_hash=f"hash_{i}",
            )
        conn.close()

        result = runner.invoke(
            cli, ["--db", str(db_path), "collections", "add-books", "1", "1", "2"]
        )
        assert result.exit_code == 0
        assert "Added 2 book(s)" in result.output

    def test_add_books_invalid_collection(self, runner: CliRunner, db_path: Path) -> None:
        """Adding to non-existent collection shows error."""
        result = runner.invoke(cli, ["--db", str(db_path), "collections", "add-books", "999", "1"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_add_books_invalid_book(self, runner: CliRunner, db_path: Path) -> None:
        """Adding non-existent book shows error."""
        runner.invoke(cli, ["--db", str(db_path), "collections", "create", "Favorites"])
        result = runner.invoke(cli, ["--db", str(db_path), "collections", "add-books", "1", "999"])
        assert result.exit_code == 1
        assert "not found" in result.output


class TestCollectionsRemoveBooks:
    """Tests for `collections remove-books` command."""

    def test_remove_books_success(self, runner: CliRunner, db_path: Path) -> None:
        """Removing books from a collection succeeds."""
        # Setup
        runner.invoke(cli, ["--db", str(db_path), "collections", "create", "Favorites"])
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        for i in range(3):
            catalog.add_book(
                BookMetadata(title=f"Book {i}", source_path=Path(f"/books/{i}.epub")),
                file_hash=f"hash_{i}",
            )
        catalog.add_books_to_collection(1, [1, 2, 3])
        conn.close()

        result = runner.invoke(
            cli, ["--db", str(db_path), "collections", "remove-books", "1", "1", "2"]
        )
        assert result.exit_code == 0
        assert "Removed 2 book(s)" in result.output

    def test_remove_books_invalid_collection(self, runner: CliRunner, db_path: Path) -> None:
        """Removing from non-existent collection shows error."""
        result = runner.invoke(
            cli, ["--db", str(db_path), "collections", "remove-books", "999", "1"]
        )
        assert result.exit_code == 1
        assert "not found" in result.output


class TestCollectionsLs:
    """Tests for `collections ls` command."""

    def test_ls_shows_collections(self, runner: CliRunner, db_path: Path) -> None:
        """ls shows all collections with counts."""
        runner.invoke(cli, ["--db", str(db_path), "collections", "create", "Favorites"])
        runner.invoke(cli, ["--db", str(db_path), "collections", "create", "To Read"])

        result = runner.invoke(cli, ["--db", str(db_path), "collections", "ls"])
        assert result.exit_code == 0
        assert "Favorites" in result.output
        assert "To Read" in result.output

    def test_ls_empty_library(self, runner: CliRunner, db_path: Path) -> None:
        """ls shows message when no collections exist."""
        result = runner.invoke(cli, ["--db", str(db_path), "collections", "ls"])
        assert result.exit_code == 0
        assert "No collections" in result.output


class TestCollectionsShow:
    """Tests for `collections show` command."""

    def test_show_shows_books(self, runner: CliRunner, db_path: Path) -> None:
        """show displays books in the collection."""
        # Setup
        runner.invoke(cli, ["--db", str(db_path), "collections", "create", "Favorites"])
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        book_id = catalog.add_book(
            BookMetadata(title="Test Book", source_path=Path("/books/test.epub")),
            file_hash="test_hash",
        )
        catalog.add_books_to_collection(1, [book_id])
        conn.close()

        result = runner.invoke(cli, ["--db", str(db_path), "collections", "show", "1"])
        assert result.exit_code == 0
        assert "Favorites" in result.output
        assert "Test Book" in result.output

    def test_show_empty_collection(self, runner: CliRunner, db_path: Path) -> None:
        """show shows message for empty collection."""
        runner.invoke(cli, ["--db", str(db_path), "collections", "create", "Favorites"])
        result = runner.invoke(cli, ["--db", str(db_path), "collections", "show", "1"])
        assert result.exit_code == 0
        assert "No books" in result.output

    def test_show_invalid_collection(self, runner: CliRunner, db_path: Path) -> None:
        """show shows error for non-existent collection."""
        result = runner.invoke(cli, ["--db", str(db_path), "collections", "show", "999"])
        assert result.exit_code == 1
        assert "not found" in result.output


class TestCollectionsRm:
    """Tests for `collections rm` command."""

    def test_rm_deletes_collection(self, runner: CliRunner, db_path: Path) -> None:
        """rm deletes the collection."""
        runner.invoke(cli, ["--db", str(db_path), "collections", "create", "To Delete"])

        result = runner.invoke(cli, ["--db", str(db_path), "collections", "rm", "1"], input="y\n")
        assert result.exit_code == 0
        assert "Deleted collection" in result.output

        # Verify it's gone
        result2 = runner.invoke(cli, ["--db", str(db_path), "collections", "show", "1"])
        assert result2.exit_code == 1

    def test_rm_invalid_collection(self, runner: CliRunner, db_path: Path) -> None:
        """rm shows error for non-existent collection."""
        result = runner.invoke(
            cli, ["--db", str(db_path), "collections", "rm", "999"], input="y\n"
        )
        assert result.exit_code == 1
        assert "not found" in result.output


class TestCollectionsRename:
    """Tests for `collections rename` command."""

    def test_rename_success(self, runner: CliRunner, db_path: Path) -> None:
        """rename changes the collection name."""
        runner.invoke(cli, ["--db", str(db_path), "collections", "create", "Old Name"])

        result = runner.invoke(
            cli, ["--db", str(db_path), "collections", "rename", "1", "New Name"]
        )
        assert result.exit_code == 0
        assert "Renamed collection" in result.output
        assert "Old Name" in result.output
        assert "New Name" in result.output

    def test_rename_invalid_collection(self, runner: CliRunner, db_path: Path) -> None:
        """rename shows error for non-existent collection."""
        result = runner.invoke(
            cli, ["--db", str(db_path), "collections", "rename", "999", "New Name"]
        )
        assert result.exit_code == 1
        assert "not found" in result.output
