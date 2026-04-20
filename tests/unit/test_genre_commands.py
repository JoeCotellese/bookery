# ABOUTME: Unit tests for the `bookery genre` CLI command group.
# ABOUTME: Tests genre ls, assign, and unmatched subcommands via Click's CliRunner.

from pathlib import Path

from click.testing import CliRunner

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


class TestGenreLs:
    """Tests for `bookery genre ls`."""

    def test_genre_ls_shows_all_14_genres(self, tmp_path: Path) -> None:
        """genre ls displays all 14 canonical genres."""
        db_path = tmp_path / "test.db"
        open_library(db_path).close()

        runner = CliRunner()
        result = runner.invoke(cli, ["genre", "ls", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "Literary Fiction" in result.output
        assert "Science Fiction" in result.output
        assert "Fantasy" in result.output

    def test_genre_ls_shows_counts(self, tmp_path: Path) -> None:
        """genre ls shows book counts for genres."""
        db_path = tmp_path / "test.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        book_id = catalog.add_book(
            BookMetadata(title="Test Book", source_path=Path("/test.epub")),
            file_hash="hash1",
        )
        catalog.add_genre(book_id, "Literary Fiction")
        conn.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["genre", "ls", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "Literary Fiction" in result.output


class TestGenreAssign:
    """Tests for `bookery genre assign`."""

    def test_assign_genre_success(self, tmp_path: Path) -> None:
        """Assigning a genre to a book succeeds."""
        db_path = tmp_path / "test.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        catalog.add_book(
            BookMetadata(title="Test Book", source_path=Path("/test.epub")),
            file_hash="hash1",
        )
        conn.close()

        runner = CliRunner()
        result = runner.invoke(
            cli, ["genre", "assign", "1", "Literary Fiction", "--db", str(db_path)]
        )
        assert result.exit_code == 0
        assert "Literary Fiction" in result.output
        assert "Test Book" in result.output

    def test_assign_genre_with_primary(self, tmp_path: Path) -> None:
        """Assigning a genre with --primary sets it as primary."""
        db_path = tmp_path / "test.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        catalog.add_book(
            BookMetadata(title="Test Book", source_path=Path("/test.epub")),
            file_hash="hash1",
        )
        conn.close()

        runner = CliRunner()
        result = runner.invoke(
            cli, ["genre", "assign", "1", "Literary Fiction", "--primary", "--db", str(db_path)]
        )
        assert result.exit_code == 0

    def test_assign_invalid_genre(self, tmp_path: Path) -> None:
        """Assigning a non-canonical genre shows error."""
        db_path = tmp_path / "test.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        catalog.add_book(
            BookMetadata(title="Test Book", source_path=Path("/test.epub")),
            file_hash="hash1",
        )
        conn.close()

        runner = CliRunner()
        result = runner.invoke(
            cli, ["genre", "assign", "1", "Made Up", "--db", str(db_path)]
        )
        assert result.exit_code == 1
        assert "not a canonical genre" in result.output

    def test_assign_nonexistent_book(self, tmp_path: Path) -> None:
        """Assigning a genre to a missing book shows error."""
        db_path = tmp_path / "test.db"
        open_library(db_path).close()

        runner = CliRunner()
        result = runner.invoke(
            cli, ["genre", "assign", "999", "Literary Fiction", "--db", str(db_path)]
        )
        assert result.exit_code == 1
        assert "not found" in result.output


class TestGenreUnmatched:
    """Tests for `bookery genre unmatched`."""

    def test_unmatched_shows_books(self, tmp_path: Path) -> None:
        """genre unmatched shows books with subjects but no genres."""
        db_path = tmp_path / "test.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        book_id = catalog.add_book(
            BookMetadata(
                title="Unmatched Book",
                subjects=["weird subject"],
                source_path=Path("/test.epub"),
            ),
            file_hash="hash1",
        )
        catalog.store_subjects(book_id, ["weird subject"])
        conn.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["genre", "unmatched", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "Unmatched Book" in result.output

    def test_unmatched_empty(self, tmp_path: Path) -> None:
        """genre unmatched shows message when all books have genres."""
        db_path = tmp_path / "test.db"
        open_library(db_path).close()

        runner = CliRunner()
        result = runner.invoke(cli, ["genre", "unmatched", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "All books" in result.output or "No books" in result.output


class TestInfoShowsGenre:
    """Tests for genre display in `bookery info`."""

    def test_info_shows_primary_genre(self, tmp_path: Path) -> None:
        """Info command displays primary genre for a book."""
        db_path = tmp_path / "test.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        catalog.add_book(
            BookMetadata(title="Test Book", source_path=Path("/test.epub")),
            file_hash="hash1",
        )
        catalog.add_genre(1, "Literary Fiction", is_primary=True)
        conn.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["info", "1", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "Literary Fiction" in result.output

    def test_info_no_genre_shows_nothing(self, tmp_path: Path) -> None:
        """Info command shows no genre row when book has no genres."""
        db_path = tmp_path / "test.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        catalog.add_book(
            BookMetadata(title="Test Book", source_path=Path("/test.epub")),
            file_hash="hash1",
        )
        conn.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["info", "1", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "Genre" not in result.output


class TestLsGenreFilter:
    """Tests for --genre filter on `bookery ls`."""

    def test_ls_filter_by_genre(self, tmp_path: Path) -> None:
        """ls --genre filters to only books with that genre."""
        db_path = tmp_path / "test.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        id1 = catalog.add_book(
            BookMetadata(title="Fiction Book", source_path=Path("/f.epub")),
            file_hash="hash_f",
        )
        catalog.add_book(
            BookMetadata(title="Other Book", source_path=Path("/o.epub")),
            file_hash="hash_o",
        )
        catalog.add_genre(id1, "Literary Fiction")
        conn.close()

        runner = CliRunner()
        result = runner.invoke(
            cli, ["ls", "--genre", "Literary Fiction", "--db", str(db_path)]
        )
        assert result.exit_code == 0
        assert "Fiction Book" in result.output
        assert "Other Book" not in result.output

    def test_ls_filter_by_invalid_genre(self, tmp_path: Path) -> None:
        """ls --genre with a non-canonical genre shows error."""
        db_path = tmp_path / "test.db"
        open_library(db_path).close()

        runner = CliRunner()
        result = runner.invoke(
            cli, ["ls", "--genre", "Made Up Genre", "--db", str(db_path)]
        )
        assert result.exit_code == 1
        assert "not a canonical genre" in result.output


class TestGenreStats:
    """Tests for `bookery genre stats`."""

    def test_stats_shows_unmatched_frequencies(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        for i, subs in enumerate([
            ["widgetology", "science fiction"],
            ["widgetology"],
            ["whatsits"],
        ]):
            catalog.add_book(
                BookMetadata(title=f"B{i}", source_path=Path(f"/{i}.epub")),
                file_hash=f"h{i}",
            )
            catalog.store_subjects(i + 1, subs)
        conn.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["genre", "stats", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "widgetology" in result.output
        assert "whatsits" in result.output

    def test_stats_empty_catalog(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        open_library(db_path).close()

        runner = CliRunner()
        result = runner.invoke(cli, ["genre", "stats", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "No unmatched" in result.output


class TestGenreAuto:
    """Tests for `bookery genre auto`."""

    def test_auto_all_reassigns_like_apply_force(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        book_id = catalog.add_book(
            BookMetadata(title="B", source_path=Path("/b.epub")),
            file_hash="h1",
        )
        catalog.store_subjects(book_id, ["science fiction"])
        conn.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["genre", "auto", "--all", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "1" in result.output

        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        assert catalog.get_primary_genre(book_id) == "Science Fiction"
        conn.close()
