# ABOUTME: End-to-end tests for the `bookery verify` CLI command.
# ABOUTME: Tests verify workflow via Click's CliRunner with real files and database.

from pathlib import Path

from click.testing import CliRunner

from bookery.cli import cli


class TestVerifyCliE2E:
    """E2E tests for the verify CLI workflow."""

    def test_verify_after_import(self, sample_epub: Path, tmp_path: Path) -> None:
        """Verify succeeds immediately after import (all files present)."""
        db_path = tmp_path / "verify.db"
        runner = CliRunner()

        result = runner.invoke(cli, ["import", str(sample_epub.parent), "--db", str(db_path)])
        assert result.exit_code == 0

        result = runner.invoke(cli, ["verify", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "1 book(s) verified" in result.output

    def test_verify_after_source_deleted(self, sample_epub: Path, tmp_path: Path) -> None:
        """Verify detects when a source file has been deleted."""
        db_path = tmp_path / "deleted.db"
        runner = CliRunner()

        result = runner.invoke(cli, ["import", str(sample_epub.parent), "--db", str(db_path)])
        assert result.exit_code == 0

        # Delete the source file
        sample_epub.unlink()

        result = runner.invoke(cli, ["verify", "--db", str(db_path)])
        assert result.exit_code == 1
        assert "Missing source" in result.output

    def test_verify_check_hash_clean(self, sample_epub: Path, tmp_path: Path) -> None:
        """Verify --check-hash passes when files are unchanged."""
        db_path = tmp_path / "hashclean.db"
        runner = CliRunner()

        result = runner.invoke(cli, ["import", str(sample_epub.parent), "--db", str(db_path)])
        assert result.exit_code == 0

        result = runner.invoke(cli, ["verify", "--check-hash", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "1 book(s) verified" in result.output

    def test_verify_check_hash_modified(self, sample_epub: Path, tmp_path: Path) -> None:
        """Verify --check-hash detects modified source files."""
        db_path = tmp_path / "hashmod.db"
        runner = CliRunner()

        result = runner.invoke(cli, ["import", str(sample_epub.parent), "--db", str(db_path)])
        assert result.exit_code == 0

        # Modify the source file
        sample_epub.write_text("corrupted content")

        result = runner.invoke(cli, ["verify", "--check-hash", "--db", str(db_path)])
        assert result.exit_code == 1
        assert "Hash mismatch" in result.output

    def test_verify_empty_library(self, tmp_path: Path) -> None:
        """Verify handles empty library gracefully."""
        db_path = tmp_path / "empty.db"
        runner = CliRunner()

        result = runner.invoke(cli, ["verify", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "0 book(s) verified" in result.output
