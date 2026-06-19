# ABOUTME: End-to-end tests for the `bookery genre auto-assign` CLI subcommand.
# ABOUTME: Covers the canonical name plus the deprecated `genre apply` alias.

from pathlib import Path

from click.testing import CliRunner

from bookery.cli import cli
from bookery.cli.deprecation import reset_deprecation_state
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


def _setup_db(tmp_path: Path) -> Path:
    """Create a test DB with a mix of books for genre auto-assign testing."""
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


class TestGenreAutoAssign:
    """Tests for `bookery genre auto-assign`."""

    def test_auto_assign_assigns_genres(self, tmp_path: Path) -> None:
        """genre auto-assign assigns genres to ungenred books with matchable subjects."""
        reset_deprecation_state()
        db_path = _setup_db(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["genre", "auto-assign", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "1" in result.output  # 1 assigned
        assert "assigned" in result.output.lower() or "Applied" in result.output

    def test_auto_assign_reports_unmatched(self, tmp_path: Path) -> None:
        """genre auto-assign reports unmatched books."""
        reset_deprecation_state()
        db_path = _setup_db(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["genre", "auto-assign", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "unmatched" in result.output.lower()

    def test_auto_assign_dry_run(self, tmp_path: Path) -> None:
        """genre auto-assign --dry-run shows what would happen without writing."""
        reset_deprecation_state()
        db_path = _setup_db(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["genre", "auto-assign", "--dry-run", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "dry run" in result.output.lower() or "Dry run" in result.output

        # Verify nothing was written
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        # Murder Mystery should still have no genre
        genres = catalog.get_genres_for_book(1)
        assert genres == []
        conn.close()

    def test_auto_assign_force(self, tmp_path: Path) -> None:
        """genre auto-assign --force re-evaluates all books with subjects."""
        reset_deprecation_state()
        db_path = _setup_db(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["genre", "auto-assign", "--force", "--db", str(db_path)])
        assert result.exit_code == 0
        # Should show assignments for both matchable books
        assert "2" in result.output  # 2 assigned (Murder Mystery + Sci-Fi Classic)

    def test_auto_assign_idempotent(self, tmp_path: Path) -> None:
        """Running auto-assign twice produces no new assignments on second run."""
        reset_deprecation_state()
        db_path = _setup_db(tmp_path)
        runner = CliRunner()
        # First run
        runner.invoke(cli, ["genre", "auto-assign", "--db", str(db_path)])
        # Second run
        result = runner.invoke(cli, ["genre", "auto-assign", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "0" in result.output  # 0 newly assigned

    def test_auto_assign_empty_catalog(self, tmp_path: Path) -> None:
        """genre auto-assign on an empty catalog shows no-op message."""
        reset_deprecation_state()
        db_path = tmp_path / "empty.db"
        open_library(db_path).close()
        runner = CliRunner()
        result = runner.invoke(cli, ["genre", "auto-assign", "--db", str(db_path)])
        assert result.exit_code == 0


class TestGenreApplyDeprecatedAlias:
    """Tests for the deprecated `genre apply` alias forwarding to `auto-assign`."""

    def test_apply_alias_assigns_genres(self, tmp_path: Path) -> None:
        """The deprecated `genre apply` still assigns genres."""
        reset_deprecation_state()
        db_path = _setup_db(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["genre", "apply", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "1" in result.output
        assert "assigned" in result.output.lower() or "Applied" in result.output

    def test_apply_alias_prints_deprecation_warning(self, tmp_path: Path) -> None:
        """The deprecated `genre apply` prints a deprecation warning to stderr."""
        reset_deprecation_state()
        db_path = _setup_db(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["genre", "apply", "--db", str(db_path)])
        assert result.exit_code == 0
        assert (
            "warning: 'apply' is deprecated; use 'auto-assign' instead. "
            "This alias will be removed in a future release."
        ) in result.stderr
        # Warning must not pollute stdout.
        assert "deprecated" not in result.stdout

    def test_apply_alias_warning_emitted_once(self, tmp_path: Path) -> None:
        """The alias warning is emitted at most once per invocation."""
        reset_deprecation_state()
        db_path = _setup_db(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["genre", "apply", "--db", str(db_path)])
        assert result.exit_code == 0
        assert result.stderr.count("warning: 'apply' is deprecated") == 1

    def test_apply_alias_forwards_dry_run(self, tmp_path: Path) -> None:
        """The deprecated alias forwards --dry-run to the canonical command."""
        reset_deprecation_state()
        db_path = _setup_db(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["genre", "apply", "--dry-run", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "dry run" in result.output.lower() or "Dry run" in result.output

    def test_apply_alias_forwards_force(self, tmp_path: Path) -> None:
        """The deprecated alias forwards --force to the canonical command."""
        reset_deprecation_state()
        db_path = _setup_db(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["genre", "apply", "--force", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "2" in result.output  # 2 assigned via --force

    def test_apply_alias_help_marks_deprecation(self) -> None:
        """`genre apply --help` indicates the alias is deprecated."""
        reset_deprecation_state()
        runner = CliRunner()
        result = runner.invoke(cli, ["genre", "apply", "--help"])
        assert result.exit_code == 0
        assert "deprecated" in result.stdout.lower()

    def test_apply_alias_hidden_from_genre_help(self) -> None:
        """`genre --help` does not list the deprecated alias."""
        reset_deprecation_state()
        runner = CliRunner()
        result = runner.invoke(cli, ["genre", "--help"])
        assert result.exit_code == 0
        # Canonical name is listed
        assert "auto-assign" in result.stdout
        # Hidden alias is not listed in the group help. The two-space column
        # prefix is how Click formats command-list rows.
        assert "\n  apply " not in result.stdout
