# ABOUTME: End-to-end tests for the `bookery genre` CLI command group.
# ABOUTME: Tests full genre workflow via Click's CliRunner with real database.

from pathlib import Path

from click.testing import CliRunner

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


class TestGenreCliE2E:
    """E2E tests for the genre CLI workflow."""

    def test_full_genre_lifecycle(self, sample_epub: Path, tmp_path: Path) -> None:
        """Full lifecycle: import -> genre ls -> assign -> info -> ls -> unmatched."""
        db_path = tmp_path / "e2e.db"
        runner = CliRunner()

        # Import a book
        result = runner.invoke(cli, ["import", str(sample_epub.parent), "--db", str(db_path)])
        assert result.exit_code == 0
        assert "1 added" in result.output

        # List genres — all 14 with 0 counts
        result = runner.invoke(cli, ["genre", "ls", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "Literary Fiction" in result.output
        assert "Science Fiction" in result.output

        # Assign a genre
        result = runner.invoke(
            cli, ["genre", "assign", "1", "Literary Fiction", "--primary", "--db", str(db_path)]
        )
        assert result.exit_code == 0
        assert "Literary Fiction" in result.output

        # Assign another genre
        result = runner.invoke(
            cli, ["genre", "assign", "1", "Mystery & Thriller", "--db", str(db_path)]
        )
        assert result.exit_code == 0

        # Info shows genre
        result = runner.invoke(cli, ["info", "1", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "Literary Fiction" in result.output

        # ls --genre filters
        result = runner.invoke(
            cli, ["ls", "--genre", "Literary Fiction", "--db", str(db_path)]
        )
        assert result.exit_code == 0
        assert "The Name of the Rose" in result.output

        # ls --genre with empty genre shows no books
        result = runner.invoke(
            cli, ["ls", "--genre", "Horror", "--db", str(db_path)]
        )
        assert result.exit_code == 0
        assert "No books" in result.output

        # Unmatched shows nothing (book has genres)
        result = runner.invoke(cli, ["genre", "unmatched", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "No books" in result.output

    def test_genre_assign_invalid_genre_errors(self, tmp_path: Path) -> None:
        """Assigning an invalid genre via CLI fails gracefully."""
        db_path = tmp_path / "err.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        catalog.add_book(
            BookMetadata(title="Test", source_path=Path("/t.epub")),
            file_hash="h1",
        )
        conn.close()

        runner = CliRunner()
        result = runner.invoke(
            cli, ["genre", "assign", "1", "Fake Genre", "--db", str(db_path)]
        )
        assert result.exit_code == 1
        assert "not a canonical genre" in result.output

    def test_unmatched_shows_books_with_subjects_no_genre(self, tmp_path: Path) -> None:
        """Genre unmatched shows books that have stored subjects but no genre."""
        db_path = tmp_path / "unmatched.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        book_id = catalog.add_book(
            BookMetadata(title="Needs Genre", source_path=Path("/ng.epub")),
            file_hash="ng_hash",
        )
        catalog.store_subjects(book_id, ["weird topic", "obscure field"])
        conn.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["genre", "unmatched", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "Needs Genre" in result.output
        assert "weird topic" in result.output
