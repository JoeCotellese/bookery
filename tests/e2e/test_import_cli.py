# ABOUTME: End-to-end tests for the `bookery import` CLI command with DB integration.
# ABOUTME: Validates command output, DB creation, --db flag, and dedup reporting.

import shutil
from pathlib import Path

from click.testing import CliRunner

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library


class TestImportCommand:
    """E2E tests for the bookery import command."""

    def test_import_creates_db(
        self, sample_epub: Path, tmp_path: Path,
    ) -> None:
        """Import creates a database file and catalogs the EPUB."""
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        shutil.copy(sample_epub, scan_dir / "rose.epub")

        db_path = tmp_path / "test.db"
        runner = CliRunner()
        result = runner.invoke(
            cli, ["import", str(scan_dir), "--db", str(db_path)],
        )

        assert result.exit_code == 0
        assert db_path.exists()

        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        records = catalog.list_all()
        assert len(records) == 1
        assert records[0].metadata.title == "The Name of the Rose"
        conn.close()

    def test_import_shows_summary(
        self, sample_epub: Path, minimal_epub: Path, tmp_path: Path,
    ) -> None:
        """Import output shows added count."""
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        shutil.copy(sample_epub, scan_dir / "rose.epub")
        shutil.copy(minimal_epub, scan_dir / "minimal.epub")

        db_path = tmp_path / "test.db"
        runner = CliRunner()
        result = runner.invoke(
            cli, ["import", str(scan_dir), "--db", str(db_path)],
        )

        assert result.exit_code == 0
        assert "2" in result.output  # 2 files processed
        assert "added" in result.output.lower()

    def test_import_reimport_shows_skipped(
        self, sample_epub: Path, tmp_path: Path,
    ) -> None:
        """Second import of same files shows skipped count."""
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        shutil.copy(sample_epub, scan_dir / "rose.epub")

        db_path = tmp_path / "test.db"
        runner = CliRunner()

        runner.invoke(cli, ["import", str(scan_dir), "--db", str(db_path)])
        result = runner.invoke(
            cli, ["import", str(scan_dir), "--db", str(db_path)],
        )

        assert result.exit_code == 0
        assert "skipped" in result.output.lower()

    def test_import_empty_directory(self, tmp_path: Path) -> None:
        """Import command reports when no EPUBs are found."""
        db_path = tmp_path / "test.db"
        runner = CliRunner()
        result = runner.invoke(
            cli, ["import", str(tmp_path), "--db", str(db_path)],
        )

        assert result.exit_code == 0
        assert "No EPUB files found" in result.output

    def test_import_handles_corrupt_files(
        self, sample_epub: Path, corrupt_epub: Path, tmp_path: Path,
    ) -> None:
        """Import handles corrupt files without crashing."""
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        shutil.copy(sample_epub, scan_dir / "rose.epub")
        shutil.copy(corrupt_epub, scan_dir / "bad.epub")

        db_path = tmp_path / "test.db"
        runner = CliRunner()
        result = runner.invoke(
            cli, ["import", str(scan_dir), "--db", str(db_path)],
        )

        assert result.exit_code == 0
        assert "error" in result.output.lower()

        # Good file should still be imported
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        records = catalog.list_all()
        assert len(records) == 1
        conn.close()
