# ABOUTME: End-to-end tests for the `bookery folder` CLI command.
# ABOUTME: Drives the full CLI through Click against a real on-disk DB and folder.

from pathlib import Path

from click.testing import CliRunner

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


def _seed_book(db_path: Path, title: str, folder: Path) -> int:
    """Add a single book with an on-disk output_path and return its ID."""
    folder.mkdir(parents=True, exist_ok=True)
    conn = open_library(db_path)
    try:
        catalog = LibraryCatalog(conn)
        return catalog.add_book(
            BookMetadata(title=title, source_path=Path("/src/x.epub")),
            file_hash="seed_hash",
            output_path=folder,
        )
    finally:
        conn.close()


class TestFolderCliE2E:
    """E2E tests covering the full folder command flow against a real DB."""

    def test_print_folder_by_id(self, tmp_path: Path) -> None:
        db_path = tmp_path / "e2e.db"
        folder = tmp_path / "library" / "The_Hobbit"
        book_id = _seed_book(db_path, "The Hobbit", folder)

        runner = CliRunner()
        result = runner.invoke(
            cli, ["folder", str(book_id), "--print", "--db", str(db_path)]
        )
        assert result.exit_code == 0, result.output

        printed = result.output.strip().splitlines()[-1]
        printed_path = Path(printed)
        assert printed_path.exists()
        assert printed_path.is_dir()
        assert printed_path == folder

    def test_print_folder_by_title_substring(self, tmp_path: Path) -> None:
        db_path = tmp_path / "e2e.db"
        folder = tmp_path / "library" / "Hobbit"
        _seed_book(db_path, "The Hobbit", folder)

        runner = CliRunner()
        result = runner.invoke(
            cli, ["folder", "Hobbit", "--print", "--db", str(db_path)]
        )
        assert result.exit_code == 0, result.output
        assert str(folder) in result.output
