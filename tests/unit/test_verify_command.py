# ABOUTME: Unit tests for the `bookery verify` CLI command.
# ABOUTME: Tests output formatting, exit codes, and --check-hash flag.

from pathlib import Path

from click.testing import CliRunner

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.db.hashing import compute_file_hash
from bookery.metadata.types import BookMetadata


class TestVerifyCommand:
    """Tests for `bookery verify`."""

    def test_verify_clean_library(self, tmp_path: Path) -> None:
        """Verify shows success message when all books check out."""
        db_path = tmp_path / "clean.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)

        source = tmp_path / "book.epub"
        source.write_text("content")
        catalog.add_book(
            BookMetadata(title="Good Book", source_path=source),
            file_hash=compute_file_hash(source),
        )
        conn.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["verify", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "1 book(s) verified" in result.output

    def test_verify_empty_library(self, tmp_path: Path) -> None:
        """Verify handles empty library gracefully."""
        db_path = tmp_path / "empty.db"
        open_library(db_path).close()

        runner = CliRunner()
        result = runner.invoke(cli, ["verify", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "0 book(s) verified" in result.output

    def test_verify_missing_source(self, tmp_path: Path) -> None:
        """Verify flags books with missing source files."""
        db_path = tmp_path / "missing.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)

        catalog.add_book(
            BookMetadata(title="Ghost", source_path=Path("/nonexistent.epub")),
            file_hash="ghost_hash",
        )
        conn.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["verify", "--db", str(db_path)])
        assert result.exit_code == 1
        assert "Ghost" in result.output
        assert "missing source" in result.output.lower()

    def test_verify_missing_output(self, tmp_path: Path) -> None:
        """Verify flags books with missing output files."""
        db_path = tmp_path / "outmiss.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)

        source = tmp_path / "real.epub"
        source.write_text("content")
        book_id = catalog.add_book(
            BookMetadata(title="Outless", source_path=source),
            file_hash="real_hash",
        )
        catalog.set_output_path(book_id, Path("/nonexistent/output.epub"))
        conn.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["verify", "--db", str(db_path)])
        assert result.exit_code == 1
        assert "Outless" in result.output
        assert "missing output" in result.output.lower()

    def test_verify_with_check_hash(self, tmp_path: Path) -> None:
        """Verify --check-hash flags modified files."""
        db_path = tmp_path / "hash.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)

        source = tmp_path / "modded.epub"
        source.write_text("original")
        original_hash = compute_file_hash(source)

        catalog.add_book(
            BookMetadata(title="Modified", source_path=source),
            file_hash=original_hash,
        )
        conn.close()

        source.write_text("changed content")

        runner = CliRunner()
        result = runner.invoke(cli, ["verify", "--check-hash", "--db", str(db_path)])
        assert result.exit_code == 1
        assert "Modified" in result.output
        assert "hash mismatch" in result.output.lower()

    def test_verify_summary_line(self, tmp_path: Path) -> None:
        """Verify shows issue count in summary."""
        db_path = tmp_path / "summary.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)

        catalog.add_book(
            BookMetadata(title="Missing A", source_path=Path("/gone1.epub")),
            file_hash="h1",
        )
        catalog.add_book(
            BookMetadata(title="Missing B", source_path=Path("/gone2.epub")),
            file_hash="h2",
        )
        conn.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["verify", "--db", str(db_path)])
        assert result.exit_code == 1
        assert "2 issue(s)" in result.output
