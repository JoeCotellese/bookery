# ABOUTME: Unit tests for the ls, info, and search CLI commands.
# ABOUTME: Validates output format, empty states, and error handling.

from pathlib import Path

from click.testing import CliRunner

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


def _seed_catalog(db_path: Path) -> None:
    """Create a DB and populate it with sample books."""
    conn = open_library(db_path)
    catalog = LibraryCatalog(conn)

    catalog.add_book(
        BookMetadata(
            title="The Name of the Rose",
            authors=["Umberto Eco"],
            language="eng",
            isbn="9780156001311",
            description="A mystery in a medieval monastery.",
            series="Adso of Melk",
            series_index=1.0,
            source_path=Path("/books/rose.epub"),
        ),
        file_hash="hash_rose",
    )
    catalog.add_book(
        BookMetadata(
            title="Foucault's Pendulum",
            authors=["Umberto Eco"],
            language="eng",
            description="A conspiracy thriller.",
            source_path=Path("/books/fp.epub"),
        ),
        file_hash="hash_fp",
    )
    catalog.add_book(
        BookMetadata(
            title="The Alexandria Link",
            authors=["Steve Berry"],
            language="eng",
            series="Cotton Malone",
            series_index=2.0,
            source_path=Path("/books/al.epub"),
        ),
        file_hash="hash_al",
    )
    conn.close()


class TestLsCommand:
    """Tests for bookery ls."""

    def test_ls_shows_all_books(self, tmp_path: Path) -> None:
        """ls lists all cataloged books."""
        db_path = tmp_path / "lib.db"
        _seed_catalog(db_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["ls", "--db", str(db_path)])

        assert result.exit_code == 0
        assert "The Name of the Rose" in result.output
        assert "Foucault's Pendulum" in result.output
        assert "The Alexandria Link" in result.output

    def test_ls_shows_author(self, tmp_path: Path) -> None:
        """ls displays author information."""
        db_path = tmp_path / "lib.db"
        _seed_catalog(db_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["ls", "--db", str(db_path)])

        assert "Umberto Eco" in result.output
        assert "Steve Berry" in result.output

    def test_ls_shows_series(self, tmp_path: Path) -> None:
        """ls displays series information."""
        db_path = tmp_path / "lib.db"
        _seed_catalog(db_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["ls", "--db", str(db_path)])

        assert "Cotton Malone" in result.output

    def test_ls_series_filter(self, tmp_path: Path) -> None:
        """ls --series filters to a specific series."""
        db_path = tmp_path / "lib.db"
        _seed_catalog(db_path)

        runner = CliRunner()
        result = runner.invoke(
            cli, ["ls", "--db", str(db_path), "--series", "Cotton Malone"],
        )

        assert result.exit_code == 0
        assert "The Alexandria Link" in result.output
        assert "The Name of the Rose" not in result.output

    def test_ls_empty_db(self, tmp_path: Path) -> None:
        """ls shows a message when the library is empty."""
        db_path = tmp_path / "lib.db"
        open_library(db_path).close()

        runner = CliRunner()
        result = runner.invoke(cli, ["ls", "--db", str(db_path)])

        assert result.exit_code == 0
        assert "No books" in result.output


class TestInfoCommand:
    """Tests for bookery info."""

    def test_info_shows_full_detail(self, tmp_path: Path) -> None:
        """info <id> shows all metadata fields."""
        db_path = tmp_path / "lib.db"
        _seed_catalog(db_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["info", "1", "--db", str(db_path)])

        assert result.exit_code == 0
        assert "The Name of the Rose" in result.output
        assert "Umberto Eco" in result.output
        assert "9780156001311" in result.output
        assert "medieval monastery" in result.output

    def test_info_nonexistent_shows_error(self, tmp_path: Path) -> None:
        """info for unknown ID shows an error."""
        db_path = tmp_path / "lib.db"
        open_library(db_path).close()

        runner = CliRunner()
        result = runner.invoke(cli, ["info", "999", "--db", str(db_path)])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()


class TestSearchCommand:
    """Tests for bookery search."""

    def test_search_finds_matching_books(self, tmp_path: Path) -> None:
        """search finds books by title keyword."""
        db_path = tmp_path / "lib.db"
        _seed_catalog(db_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["search", "Rose", "--db", str(db_path)])

        assert result.exit_code == 0
        assert "The Name of the Rose" in result.output

    def test_search_by_author(self, tmp_path: Path) -> None:
        """search finds books by author."""
        db_path = tmp_path / "lib.db"
        _seed_catalog(db_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["search", "Eco", "--db", str(db_path)])

        assert result.exit_code == 0
        assert "The Name of the Rose" in result.output
        assert "Foucault's Pendulum" in result.output

    def test_search_no_results(self, tmp_path: Path) -> None:
        """search shows a message when nothing matches."""
        db_path = tmp_path / "lib.db"
        _seed_catalog(db_path)

        runner = CliRunner()
        result = runner.invoke(
            cli, ["search", "zzz_nonexistent", "--db", str(db_path)],
        )

        assert result.exit_code == 0
        assert "No results" in result.output
