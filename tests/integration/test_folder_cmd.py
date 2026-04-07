# ABOUTME: Integration tests for the `bookery folder` CLI command.
# ABOUTME: Uses a real tmp SQLite database with the file-manager opener mocked.

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata
from bookery.util.file_manager import Headless, Opened, OpenerFailed


@pytest.fixture()
def db_with_books(tmp_path: Path) -> tuple[Path, dict[str, int]]:
    """Seed a real SQLite db with a few books that have on-disk folders."""
    db_path = tmp_path / "library.db"
    conn = open_library(db_path)
    catalog = LibraryCatalog(conn)

    out_root = tmp_path / "library"
    out_root.mkdir()

    ids: dict[str, int] = {}
    for title, hash_ in [
        ("The Hobbit", "h1"),
        ("Dune", "h2"),
        ("Dune Messiah", "h3"),
    ]:
        folder = out_root / title.replace(" ", "_")
        folder.mkdir()
        book_id = catalog.add_book(
            BookMetadata(title=title, source_path=Path(f"/src/{hash_}.epub")),
            file_hash=hash_,
            output_path=folder,
        )
        ids[title] = book_id

    conn.close()
    return db_path, ids


class TestFolderCommandPrint:
    def test_print_by_id_prints_path_and_exits_zero(
        self, db_with_books: tuple[Path, dict[str, int]]
    ) -> None:
        db_path, ids = db_with_books
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["folder", str(ids["The Hobbit"]), "--print", "--db", str(db_path)],
        )
        assert result.exit_code == 0, result.output
        assert "The_Hobbit" in result.output


class TestFolderCommandOpen:
    def test_open_by_id_invokes_opener(
        self, db_with_books: tuple[Path, dict[str, int]]
    ) -> None:
        db_path, ids = db_with_books
        runner = CliRunner()
        with patch(
            "bookery.cli.commands.folder_cmd.open_in_file_manager",
            return_value=Opened(),
        ) as mock_open:
            result = runner.invoke(
                cli,
                ["folder", str(ids["The Hobbit"]), "--db", str(db_path)],
            )
        assert result.exit_code == 0, result.output
        mock_open.assert_called_once()

    def test_headless_exits_zero_with_notice(
        self, db_with_books: tuple[Path, dict[str, int]]
    ) -> None:
        db_path, ids = db_with_books
        runner = CliRunner()
        with patch(
            "bookery.cli.commands.folder_cmd.open_in_file_manager",
            return_value=Headless(),
        ):
            result = runner.invoke(
                cli,
                ["folder", str(ids["The Hobbit"]), "--db", str(db_path)],
            )
        assert result.exit_code == 0, result.output
        assert "headless" in result.output.lower() or "no graphical" in result.output.lower()

    def test_opener_failure_exits_nonzero(
        self, db_with_books: tuple[Path, dict[str, int]]
    ) -> None:
        db_path, ids = db_with_books
        runner = CliRunner()
        with patch(
            "bookery.cli.commands.folder_cmd.open_in_file_manager",
            return_value=OpenerFailed("nope"),
        ):
            result = runner.invoke(
                cli,
                ["folder", str(ids["The Hobbit"]), "--db", str(db_path)],
            )
        assert result.exit_code == 1
        assert "nope" in result.output


class TestFolderCommandLookupErrors:
    def test_unknown_id_exits_one(
        self, db_with_books: tuple[Path, dict[str, int]]
    ) -> None:
        db_path, _ = db_with_books
        runner = CliRunner()
        result = runner.invoke(
            cli, ["folder", "9999", "--print", "--db", str(db_path)]
        )
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_ambiguous_title_exits_two(
        self, db_with_books: tuple[Path, dict[str, int]]
    ) -> None:
        db_path, _ = db_with_books
        runner = CliRunner()
        result = runner.invoke(
            cli, ["folder", "Dune", "--print", "--db", str(db_path)]
        )
        assert result.exit_code == 2
        assert "Dune" in result.output
        assert "Dune Messiah" in result.output

    def test_typo_returns_suggestions(
        self, db_with_books: tuple[Path, dict[str, int]]
    ) -> None:
        db_path, _ = db_with_books
        runner = CliRunner()
        result = runner.invoke(
            cli, ["folder", "Hobit", "--print", "--db", str(db_path)]
        )
        assert result.exit_code == 1
        assert "did you mean" in result.output.lower()
        assert "Hobbit" in result.output


class TestFolderCommandFilesystemErrors:
    def test_missing_folder_on_disk_exits_one(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "lib.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        ghost_folder = tmp_path / "does_not_exist"
        book_id = catalog.add_book(
            BookMetadata(title="Ghost", source_path=Path("/src/g.epub")),
            file_hash="gh",
            output_path=ghost_folder,
        )
        conn.close()

        runner = CliRunner()
        result = runner.invoke(
            cli, ["folder", str(book_id), "--print", "--db", str(db_path)]
        )
        assert result.exit_code == 1
        assert "out of sync" in result.output.lower() or "does not exist" in result.output.lower()

    def test_no_output_path_falls_back_to_source_parent(
        self, tmp_path: Path
    ) -> None:
        """When output_path is None, fall back to the parent of source_path.

        Books imported without --match never get an output_path. The folder
        command should still be useful by opening the directory containing
        the original EPUB.
        """
        db_path = tmp_path / "lib.db"
        source_dir = tmp_path / "ingest" / "Some Book"
        source_dir.mkdir(parents=True)
        source_file = source_dir / "book.epub"
        source_file.write_bytes(b"fake")

        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        book_id = catalog.add_book(
            BookMetadata(title="Pathless", source_path=source_file),
            file_hash="pl",
            # no output_path
        )
        conn.close()

        runner = CliRunner()
        result = runner.invoke(
            cli, ["folder", str(book_id), "--print", "--db", str(db_path)]
        )
        assert result.exit_code == 0, result.output
        assert str(source_dir) in result.output

