# ABOUTME: Unit tests for the bookery match command.
# ABOUTME: Tests argument handling, provider wiring, and output behavior.

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from bookery.cli import cli
from bookery.core.pipeline import WriteResult
from bookery.metadata import BookMetadata
from bookery.metadata.candidate import MetadataCandidate


def _make_candidate(title: str, confidence: float) -> MetadataCandidate:
    return MetadataCandidate(
        metadata=BookMetadata(title=title, authors=["Test Author"]),
        confidence=confidence,
        source="openlibrary",
        source_id="test-id",
    )


class TestMatchCommand:
    """Tests for the bookery match CLI command."""

    def test_match_help(self) -> None:
        """Match command has help text."""
        runner = CliRunner()
        result = runner.invoke(cli, ["match", "--help"])
        assert result.exit_code == 0
        assert "Match" in result.output or "match" in result.output

    def test_match_nonexistent_path(self) -> None:
        """Match command fails for nonexistent path."""
        runner = CliRunner()
        result = runner.invoke(cli, ["match", "/nonexistent/path.epub"])
        assert result.exit_code != 0

    def test_match_single_file_quiet(self, sample_epub: Path, tmp_path: Path) -> None:
        """Match in quiet mode with a fake provider auto-accepts high confidence."""
        output_dir = tmp_path / "output"
        candidate = _make_candidate("Matched Title", 0.95)

        with (
            patch(
                "bookery.cli.commands.match_cmd._create_provider"
            ) as mock_provider_fn,
        ):
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = [candidate]
            mock_provider.search_by_title_author.return_value = [candidate]
            mock_provider_fn.return_value = mock_provider

            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["match", str(sample_epub), "-q", "-o", str(output_dir)],
            )

        assert result.exit_code == 0
        assert "1 matched" in result.output

    def test_match_reports_skipped(self, sample_epub: Path, tmp_path: Path) -> None:
        """Match reports skipped count when no candidates found."""
        output_dir = tmp_path / "output"

        with patch(
            "bookery.cli.commands.match_cmd._create_provider"
        ) as mock_provider_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = []
            mock_provider.search_by_title_author.return_value = []
            mock_provider_fn.return_value = mock_provider

            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["match", str(sample_epub), "-q", "-o", str(output_dir)],
            )

        assert result.exit_code == 0
        assert "1 skipped" in result.output

    def test_match_directory(self, sample_epub: Path, minimal_epub: Path, tmp_path: Path) -> None:
        """Match command processes all EPUBs in a directory."""
        scan_dir = tmp_path / "books"
        scan_dir.mkdir()
        import shutil

        shutil.copy(sample_epub, scan_dir / "rose.epub")
        shutil.copy(minimal_epub, scan_dir / "minimal.epub")
        output_dir = tmp_path / "output"
        candidate = _make_candidate("Matched", 0.95)

        with patch(
            "bookery.cli.commands.match_cmd._create_provider"
        ) as mock_provider_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = [candidate]
            mock_provider.search_by_title_author.return_value = [candidate]
            mock_provider_fn.return_value = mock_provider

            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["match", str(scan_dir), "-q", "-o", str(output_dir)],
            )

        assert result.exit_code == 0
        assert "2 matched" in result.output

    def test_match_output_dir_default(self, sample_epub: Path, tmp_path: Path) -> None:
        """Without -o, output directory defaults to ./bookery-output."""
        candidate = _make_candidate("Matched", 0.95)

        with (
            patch(
                "bookery.cli.commands.match_cmd._create_provider"
            ) as mock_provider_fn,
            patch(
                "bookery.cli.commands.match_cmd.apply_metadata_safely"
            ) as mock_apply,
        ):
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = []
            mock_provider.search_by_title_author.return_value = [candidate]
            mock_provider_fn.return_value = mock_provider
            mock_apply.return_value = WriteResult(
                path=tmp_path / "fake_output.epub",
                success=True,
                verified_fields=[],
            )

            runner = CliRunner()
            result = runner.invoke(cli, ["match", str(sample_epub), "-q"])

        assert result.exit_code == 0
        # apply_metadata_safely should have been called with a Path ending in bookery-output
        call_args = mock_apply.call_args
        output_dir_used = call_args[0][2]
        assert "bookery-output" in str(output_dir_used)
