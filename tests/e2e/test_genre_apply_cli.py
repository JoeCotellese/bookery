# ABOUTME: End-to-end tests for the `bookery genre apply` CLI subcommand.
# ABOUTME: Tests CLI invocation, flags, and output format via Click's CliRunner.

from pathlib import Path

from click.testing import CliRunner

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


def _setup_db(tmp_path: Path) -> Path:
    """Create a test DB with a mix of books for genre apply testing."""
    db_path = tmp_path / "test.db"
    conn = open_library(db_path)
    catalog = LibraryCatalog(conn)

    # Book with matchable subjects, no genre
    id1 = catalog.add_book(
        BookMetadata(title="Murder Mystery", source_path=Path("/m.epub")),
        file_hash="hash_m",
    )
    catalog.store_subjects(id1, ["mystery", "detective fiction"])

    # Book with unmatchable subjects, no genre
    id2 = catalog.add_book(
        BookMetadata(title="Weird Book", source_path=Path("/w.epub")),
        file_hash="hash_w",
    )
    catalog.store_subjects(id2, ["xyzzy", "plugh"])

    # Book already genred
    id3 = catalog.add_book(
        BookMetadata(title="Sci-Fi Classic", source_path=Path("/s.epub")),
        file_hash="hash_s",
    )
    catalog.store_subjects(id3, ["science fiction"])
    catalog.add_genre(id3, "Science Fiction", is_primary=True)

    # Book with no subjects
    catalog.add_book(
        BookMetadata(title="No Subjects", source_path=Path("/n.epub")),
        file_hash="hash_n",
    )

    conn.close()
    return db_path


class TestGenreApply:
    """Tests for `bookery genre apply`."""

    def test_apply_assigns_genres(self, tmp_path: Path) -> None:
        """genre apply assigns genres to ungenred books with matchable subjects."""
        db_path = _setup_db(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["genre", "apply", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "1" in result.output  # 1 assigned
        assert "assigned" in result.output.lower() or "Applied" in result.output

    def test_apply_reports_unmatched(self, tmp_path: Path) -> None:
        """genre apply reports unmatched books."""
        db_path = _setup_db(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["genre", "apply", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "unmatched" in result.output.lower()

    def test_apply_dry_run(self, tmp_path: Path) -> None:
        """genre apply --dry-run shows what would happen without writing."""
        db_path = _setup_db(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["genre", "apply", "--dry-run", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "dry run" in result.output.lower() or "Dry run" in result.output

        # Verify nothing was written
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        # Murder Mystery should still have no genre
        genres = catalog.get_genres_for_book(1)
        assert genres == []
        conn.close()

    def test_apply_force(self, tmp_path: Path) -> None:
        """genre apply --force re-evaluates all books with subjects."""
        db_path = _setup_db(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["genre", "apply", "--force", "--db", str(db_path)])
        assert result.exit_code == 0
        # Should show assignments for both matchable books
        assert "2" in result.output  # 2 assigned (Murder Mystery + Sci-Fi Classic)

    def test_apply_idempotent(self, tmp_path: Path) -> None:
        """Running apply twice produces no new assignments on second run."""
        db_path = _setup_db(tmp_path)
        runner = CliRunner()
        # First run
        runner.invoke(cli, ["genre", "apply", "--db", str(db_path)])
        # Second run
        result = runner.invoke(cli, ["genre", "apply", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "0" in result.output  # 0 newly assigned

    def test_apply_empty_catalog(self, tmp_path: Path) -> None:
        """genre apply on an empty catalog shows no-op message."""
        db_path = tmp_path / "empty.db"
        open_library(db_path).close()
        runner = CliRunner()
        result = runner.invoke(cli, ["genre", "apply", "--db", str(db_path)])
        assert result.exit_code == 0
