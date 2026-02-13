# ABOUTME: End-to-end tests for the `bookery inventory` CLI command.
# ABOUTME: Tests inventory workflow via Click's CliRunner with temp directory trees.

import json
from pathlib import Path

from click.testing import CliRunner

from bookery.cli import cli


class TestInventoryCliRichOutput:
    """E2E tests for inventory command Rich (default) output."""

    def test_empty_directory(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["inventory", str(tmp_path)])
        assert result.exit_code == 0
        assert "0 book(s) scanned" in result.output

    def test_format_summary_table(self, calibre_tree: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["inventory", str(calibre_tree)])
        assert result.exit_code == 0
        # Should contain format counts
        assert ".epub" in result.output
        assert ".mobi" in result.output
        assert ".pdf" in result.output

    def test_missing_count_default_epub(self, calibre_tree: Path) -> None:
        """Default target format is epub; should report missing count."""
        runner = CliRunner()
        result = runner.invoke(cli, ["inventory", str(calibre_tree)])
        assert result.exit_code == 0
        assert "3 book(s) scanned" in result.output
        assert "2 missing EPUB" in result.output

    def test_missing_books_listed(self, calibre_tree: Path) -> None:
        """Books missing the target format should be listed by name."""
        runner = CliRunner()
        result = runner.invoke(cli, ["inventory", str(calibre_tree)])
        assert result.exit_code == 0
        assert "Dune" in result.output
        assert "Mystery Book" in result.output

    def test_format_flag_changes_target(self, calibre_tree: Path) -> None:
        """--format mobi should report books missing MOBI instead of EPUB."""
        runner = CliRunner()
        result = runner.invoke(cli, ["inventory", str(calibre_tree), "--format", "mobi"])
        assert result.exit_code == 0
        assert "missing MOBI" in result.output
        # Mystery Book has only PDF, should be missing MOBI
        assert "Mystery Book" in result.output

    def test_nonexistent_path(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["inventory", "/nonexistent/path"])
        assert result.exit_code != 0


class TestInventoryCliJsonOutput:
    """E2E tests for inventory command --json output."""

    def test_valid_json(self, calibre_tree: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["inventory", str(calibre_tree), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, dict)

    def test_contains_format_counts(self, calibre_tree: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["inventory", str(calibre_tree), "--json"])
        data = json.loads(result.output)
        assert ".epub" in data["format_counts"]
        assert ".mobi" in data["format_counts"]
        assert data["format_counts"][".mobi"] == 2

    def test_contains_missing_books(self, calibre_tree: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["inventory", str(calibre_tree), "--json"])
        data = json.loads(result.output)
        assert data["missing"]["target_format"] == ".epub"
        assert data["missing"]["count"] == 2
        assert len(data["missing"]["books"]) == 2

    def test_contains_total_books(self, calibre_tree: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["inventory", str(calibre_tree), "--json"])
        data = json.loads(result.output)
        assert data["total_books"] == 3
        assert "scan_root" in data

    def test_db_cross_reference_null_without_db(self, calibre_tree: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["inventory", str(calibre_tree), "--json"])
        data = json.loads(result.output)
        assert data["db_cross_reference"] is None

    def test_empty_directory_json(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["inventory", str(tmp_path), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total_books"] == 0
        assert data["format_counts"] == {}
        assert data["missing"]["count"] == 0


class TestInventoryCliDbCrossRef:
    """E2E tests for inventory --db cross-reference."""

    def _import_epub(self, runner, epub_path: Path, db_path: Path) -> None:
        """Import an EPUB into the catalog via CLI."""
        result = runner.invoke(
            cli, ["import", str(epub_path.parent), "--db", str(db_path)]
        )
        assert result.exit_code == 0

    def test_db_shows_catalog_status_rich(
        self, calibre_tree: Path, sample_epub: Path, tmp_path: Path
    ) -> None:
        """--db with Rich output shows catalog status section."""
        db_path = tmp_path / "inventory.db"
        runner = CliRunner()

        # Import the sample epub so the catalog has one entry
        self._import_epub(runner, sample_epub, db_path)

        result = runner.invoke(
            cli,
            ["inventory", str(calibre_tree), "--db", str(db_path)],
        )
        assert result.exit_code == 0
        assert "Catalog Status" in result.output
        assert "In catalog" in result.output
        assert "Not in catalog" in result.output

    def test_db_json_includes_cross_reference(
        self, calibre_tree: Path, sample_epub: Path, tmp_path: Path
    ) -> None:
        """--db with --json includes cross-reference counts."""
        db_path = tmp_path / "inventory.db"
        runner = CliRunner()

        self._import_epub(runner, sample_epub, db_path)

        result = runner.invoke(
            cli,
            ["inventory", str(calibre_tree), "--db", str(db_path), "--json"],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        xref = data["db_cross_reference"]
        assert xref is not None
        assert "in_catalog" in xref
        assert "not_in_catalog" in xref

    def test_db_empty_catalog_all_not_in_catalog(
        self, calibre_tree: Path, tmp_path: Path
    ) -> None:
        """Empty catalog → all scanned books are not in catalog."""
        db_path = tmp_path / "empty.db"
        runner = CliRunner()

        result = runner.invoke(
            cli,
            ["inventory", str(calibre_tree), "--db", str(db_path), "--json"],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        xref = data["db_cross_reference"]
        assert xref["in_catalog"] == 0
        assert xref["not_in_catalog"] == 3
