# ABOUTME: End-to-end tests for the `bookery inventory` CLI command.
# ABOUTME: Tests inventory workflow via Click's CliRunner with temp directory trees.

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
