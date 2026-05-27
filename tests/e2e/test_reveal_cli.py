# ABOUTME: End-to-end tests for the `bookery reveal` CLI command (and `folder` alias).
# ABOUTME: Drives the full CLI through Click against a real on-disk DB and folder.

from pathlib import Path

import pytest
from click.testing import CliRunner

from bookery.cli import cli
from bookery.cli.deprecation import reset_deprecation_state
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


@pytest.fixture(autouse=True)
def _reset_dedupe() -> None:
    reset_deprecation_state()


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


class TestRevealCliE2E:
    """E2E tests covering the full reveal command flow against a real DB."""

    def test_print_folder_by_id(self, tmp_path: Path) -> None:
        db_path = tmp_path / "e2e.db"
        folder = tmp_path / "library" / "The_Hobbit"
        book_id = _seed_book(db_path, "The Hobbit", folder)

        runner = CliRunner()
        result = runner.invoke(cli, ["reveal", str(book_id), "--print", "--db", str(db_path)])
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
        result = runner.invoke(cli, ["reveal", "Hobbit", "--print", "--db", str(db_path)])
        assert result.exit_code == 0, result.output
        assert str(folder) in result.output

    def test_folder_alias_still_prints_path(self, tmp_path: Path) -> None:
        """`folder` is the deprecated alias for `reveal` and must still work."""
        db_path = tmp_path / "e2e.db"
        folder = tmp_path / "library" / "Aliased"
        book_id = _seed_book(db_path, "Aliased", folder)

        runner = CliRunner()
        result = runner.invoke(cli, ["folder", str(book_id), "--print", "--db", str(db_path)])
        assert result.exit_code == 0, result.output
        assert str(folder) in result.output

    def test_folder_alias_warns_to_stderr(self, tmp_path: Path) -> None:
        db_path = tmp_path / "e2e.db"
        folder = tmp_path / "library" / "Warned"
        book_id = _seed_book(db_path, "Warned", folder)

        runner = CliRunner()
        result = runner.invoke(cli, ["folder", str(book_id), "--print", "--db", str(db_path)])
        assert result.exit_code == 0, result.output
        assert "warning: 'folder' is deprecated; use 'reveal' instead." in result.stderr
