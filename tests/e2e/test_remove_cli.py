# ABOUTME: End-to-end tests for the `bookery remove` CLI command.
# ABOUTME: Exercises prompts, -y, --keep-file, missing IDs, and multi-ID through CliRunner.

from pathlib import Path

from click.testing import CliRunner

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


def _seed_book(
    db_path: Path,
    library_root: Path,
    *,
    title: str = "The Name of the Rose",
    file_hash: str = "h1",
    relative: str = "Umberto Eco/Rose/book.epub",
    output_path: Path | None = None,
) -> tuple[int, Path]:
    """Insert a book row pointing at a real file under ``library_root``.

    Returns the new book ID and the on-disk path that was created.
    """
    if output_path is None:
        output_path = library_root / relative
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(b"fake epub bytes")

    conn = open_library(db_path)
    catalog = LibraryCatalog(conn)
    book_id = catalog.add_book(
        BookMetadata(
            title=title,
            authors=["Umberto Eco"],
            source_path=Path("/books/source.epub"),
        ),
        file_hash=file_hash,
        output_path=output_path,
    )
    conn.close()
    return book_id, output_path


class TestRemoveCliPrompt:
    def test_prompt_accept_removes_book(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lib.db"
        library_root = tmp_path / "library"
        library_root.mkdir()
        book_id, output = _seed_book(db_path, library_root)

        runner = CliRunner()
        result = runner.invoke(cli, ["remove", str(book_id), "--db", str(db_path)], input="y\n")

        assert result.exit_code == 0, result.output
        assert "Removed" in result.output
        assert not output.exists()

    def test_prompt_decline_keeps_book(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lib.db"
        library_root = tmp_path / "library"
        library_root.mkdir()
        book_id, output = _seed_book(db_path, library_root)

        runner = CliRunner()
        result = runner.invoke(cli, ["remove", str(book_id), "--db", str(db_path)], input="n\n")

        assert result.exit_code == 0
        assert output.exists()
        conn = open_library(db_path)
        assert LibraryCatalog(conn).get_by_id(book_id) is not None
        conn.close()


class TestRemoveCliYesFlag:
    def test_yes_skips_prompt(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lib.db"
        library_root = tmp_path / "library"
        library_root.mkdir()
        book_id, output = _seed_book(db_path, library_root)

        runner = CliRunner()
        result = runner.invoke(cli, ["remove", str(book_id), "-y", "--db", str(db_path)])

        assert result.exit_code == 0, result.output
        assert "Removed" in result.output
        assert not output.exists()

    def test_multi_id_with_missing(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lib.db"
        library_root = tmp_path / "library"
        library_root.mkdir()
        book_a, path_a = _seed_book(
            db_path,
            library_root,
            title="A",
            file_hash="ha",
            relative="A/Book/a.epub",
        )
        book_b, path_b = _seed_book(
            db_path,
            library_root,
            title="B",
            file_hash="hb",
            relative="B/Book/b.epub",
        )

        missing_id = 9999
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["remove", str(book_a), str(missing_id), str(book_b), "-y", "--db", str(db_path)],
        )

        # Partial failure → exit code 1, but real books are still removed.
        assert result.exit_code == 1, result.output
        assert not path_a.exists()
        assert not path_b.exists()
        assert "not found" in result.output


class TestRemoveCliKeepFile:
    def test_keep_file_preserves_disk(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lib.db"
        library_root = tmp_path / "library"
        library_root.mkdir()
        book_id, output = _seed_book(db_path, library_root)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["remove", str(book_id), "--keep-file", "-y", "--db", str(db_path)],
        )

        assert result.exit_code == 0, result.output
        assert output.exists()
        conn = open_library(db_path)
        assert LibraryCatalog(conn).get_by_id(book_id) is None
        conn.close()


class TestRemoveCliMissingFile:
    def test_missing_file_warns_but_succeeds(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lib.db"
        library_root = tmp_path / "library"
        library_root.mkdir()
        book_id, output = _seed_book(db_path, library_root)
        output.unlink()

        runner = CliRunner()
        result = runner.invoke(cli, ["remove", str(book_id), "-y", "--db", str(db_path)])

        assert result.exit_code == 0, result.output
        assert "already missing" in result.output


class TestRemoveCliUsageErrors:
    def test_no_ids_is_usage_error(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lib.db"
        # Touch the DB so we don't blow up on connection.
        open_library(db_path).close()

        runner = CliRunner()
        result = runner.invoke(cli, ["remove", "--db", str(db_path)])

        assert result.exit_code == 2

    def test_help_lists_remove(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "remove" in result.output
