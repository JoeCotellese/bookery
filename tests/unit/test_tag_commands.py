# ABOUTME: Unit tests for the `bookery tag` CLI command group.
# ABOUTME: Tests tag add, rm, and ls subcommands via Click's CliRunner.

from pathlib import Path

from click.testing import CliRunner

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


class TestTagAdd:
    """Tests for `bookery tag add`."""

    def test_tag_add_success(self, tmp_path: Path) -> None:
        """Adding a tag to a book succeeds with confirmation message."""
        db_path = tmp_path / "test.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        catalog.add_book(
            BookMetadata(title="Test Book", source_path=Path("/test.epub")),
            file_hash="hash1",
        )
        conn.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["tag", "add", "1", "fiction", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "fiction" in result.output
        assert "Test Book" in result.output

    def test_tag_add_nonexistent_book(self, tmp_path: Path) -> None:
        """Adding a tag to a nonexistent book shows an error."""
        db_path = tmp_path / "test.db"
        open_library(db_path).close()

        runner = CliRunner()
        result = runner.invoke(cli, ["tag", "add", "999", "fiction", "--db", str(db_path)])
        assert result.exit_code == 1
        assert "not found" in result.output


class TestTagRm:
    """Tests for `bookery tag rm`."""

    def test_tag_rm_success(self, tmp_path: Path) -> None:
        """Removing a tag from a book succeeds with confirmation."""
        db_path = tmp_path / "test.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        catalog.add_book(
            BookMetadata(title="Test Book", source_path=Path("/test.epub")),
            file_hash="hash1",
        )
        catalog.add_tag(1, "fiction")
        conn.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["tag", "rm", "1", "fiction", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "Removed" in result.output

    def test_tag_rm_nonexistent_tag(self, tmp_path: Path) -> None:
        """Removing a nonexistent tag shows an error."""
        db_path = tmp_path / "test.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        catalog.add_book(
            BookMetadata(title="Test Book", source_path=Path("/test.epub")),
            file_hash="hash1",
        )
        conn.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["tag", "rm", "1", "nope", "--db", str(db_path)])
        assert result.exit_code == 1
        assert "not found" in result.output


class TestTagLs:
    """Tests for `bookery tag ls`."""

    def test_tag_ls_empty(self, tmp_path: Path) -> None:
        """Listing tags when none exist shows appropriate message."""
        db_path = tmp_path / "test.db"
        open_library(db_path).close()

        runner = CliRunner()
        result = runner.invoke(cli, ["tag", "ls", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "No tags" in result.output

    def test_tag_ls_shows_tags_with_counts(self, tmp_path: Path) -> None:
        """Listing tags shows tag names and book counts."""
        db_path = tmp_path / "test.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        id1 = catalog.add_book(
            BookMetadata(title="Book A", source_path=Path("/a.epub")),
            file_hash="hash_a",
        )
        id2 = catalog.add_book(
            BookMetadata(title="Book B", source_path=Path("/b.epub")),
            file_hash="hash_b",
        )
        catalog.add_tag(id1, "fiction")
        catalog.add_tag(id2, "fiction")
        catalog.add_tag(id1, "mystery")
        conn.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["tag", "ls", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "fiction" in result.output
        assert "mystery" in result.output


class TestInfoShowsTags:
    """Tests for tags display in `bookery info`."""

    def test_info_shows_tags(self, tmp_path: Path) -> None:
        """Info command displays tags for a book."""
        db_path = tmp_path / "test.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        catalog.add_book(
            BookMetadata(title="Test Book", source_path=Path("/test.epub")),
            file_hash="hash1",
        )
        catalog.add_tag(1, "fiction")
        catalog.add_tag(1, "mystery")
        conn.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["info", "1", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "fiction" in result.output
        assert "mystery" in result.output

    def test_info_no_tags_shows_none(self, tmp_path: Path) -> None:
        """Info command shows no tags row when book has no tags."""
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
        # "Tags" row should not appear when there are no tags
        assert "Tags" not in result.output


class TestLsTagFilter:
    """Tests for --tag filter on `bookery ls`."""

    def test_ls_filter_by_tag(self, tmp_path: Path) -> None:
        """ls --tag filters to only books with that tag."""
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
        catalog.add_tag(id1, "fiction")
        conn.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["ls", "--tag", "fiction", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "Fiction Book" in result.output
        assert "Other Book" not in result.output

    def test_ls_filter_by_nonexistent_tag(self, tmp_path: Path) -> None:
        """ls --tag with a nonexistent tag shows error."""
        db_path = tmp_path / "test.db"
        open_library(db_path).close()

        runner = CliRunner()
        result = runner.invoke(cli, ["ls", "--tag", "nope", "--db", str(db_path)])
        assert result.exit_code == 1
        assert "not found" in result.output
