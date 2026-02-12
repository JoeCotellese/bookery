# ABOUTME: End-to-end tests for the Bookery CLI.
# ABOUTME: Tests CLI commands via Click's CliRunner with real EPUB fixtures.

import shutil
from pathlib import Path

from click.testing import CliRunner

from bookery.cli import cli


class TestCliInspect:
    """E2e tests for `bookery inspect`."""

    def test_inspect_shows_metadata(self, sample_epub: Path) -> None:
        """Inspect command displays metadata for a valid EPUB."""
        runner = CliRunner()
        result = runner.invoke(cli, ["inspect", str(sample_epub)])
        assert result.exit_code == 0
        assert "The Name of the Rose" in result.output
        assert "Umberto Eco" in result.output

    def test_inspect_shows_language(self, sample_epub: Path) -> None:
        """Inspect command displays language field."""
        runner = CliRunner()
        result = runner.invoke(cli, ["inspect", str(sample_epub)])
        assert result.exit_code == 0
        assert "en" in result.output

    def test_inspect_shows_publisher(self, sample_epub: Path) -> None:
        """Inspect command displays publisher field."""
        runner = CliRunner()
        result = runner.invoke(cli, ["inspect", str(sample_epub)])
        assert result.exit_code == 0
        assert "Harcourt" in result.output

    def test_inspect_nonexistent_file_fails(self) -> None:
        """Inspect command fails gracefully for nonexistent file."""
        runner = CliRunner()
        result = runner.invoke(cli, ["inspect", "/nonexistent/path.epub"])
        assert result.exit_code != 0

    def test_inspect_corrupt_epub_reports_error(self, corrupt_epub: Path) -> None:
        """Inspect command reports a clear error for corrupt files."""
        runner = CliRunner()
        result = runner.invoke(cli, ["inspect", str(corrupt_epub)])
        assert result.exit_code == 1
        assert "Error" in result.output


class TestCliImport:
    """E2e tests for `bookery import`."""

    def test_import_scans_directory(self, sample_epub: Path) -> None:
        """Import command finds and displays EPUBs in a directory."""
        runner = CliRunner()
        result = runner.invoke(cli, ["import", str(sample_epub.parent)])
        assert result.exit_code == 0
        assert "The Name of the Rose" in result.output
        assert "1" in result.output  # At least 1 file found

    def test_import_shows_multiple_files(
        self, sample_epub: Path, minimal_epub: Path
    ) -> None:
        """Import command shows all EPUBs found in directory."""
        scan_dir = sample_epub.parent / "scan"
        scan_dir.mkdir()
        shutil.copy(sample_epub, scan_dir / "rose.epub")
        shutil.copy(minimal_epub, scan_dir / "minimal.epub")

        runner = CliRunner()
        result = runner.invoke(cli, ["import", str(scan_dir)])
        assert result.exit_code == 0
        assert "The Name of the Rose" in result.output
        assert "Untitled Book" in result.output
        assert "2" in result.output  # 2 files found

    def test_import_empty_directory(self, tmp_path: Path) -> None:
        """Import command reports when no EPUBs are found."""
        runner = CliRunner()
        result = runner.invoke(cli, ["import", str(tmp_path)])
        assert result.exit_code == 0
        assert "No EPUB files found" in result.output

    def test_import_handles_corrupt_files(
        self, sample_epub: Path, corrupt_epub: Path
    ) -> None:
        """Import command handles corrupt files without crashing."""
        scan_dir = sample_epub.parent / "scan"
        scan_dir.mkdir()
        shutil.copy(sample_epub, scan_dir / "rose.epub")
        shutil.copy(corrupt_epub, scan_dir / "bad.epub")

        runner = CliRunner()
        result = runner.invoke(cli, ["import", str(scan_dir)])
        assert result.exit_code == 0
        assert "could not be read" in result.output
        assert "The Name of the Rose" in result.output


class TestCliVersion:
    """E2e tests for version flag."""

    def test_version(self) -> None:
        """--version flag shows version."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output
