# ABOUTME: Unit tests for the bookery match command.
# ABOUTME: Tests argument handling, provider wiring, output, threshold, and resume behavior.

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
        import shutil

        scan_dir = tmp_path / "books"
        scan_dir.mkdir()
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


class TestThresholdOption:
    """Tests for --threshold / -t CLI option."""

    def test_threshold_option_passed_to_review(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        """--threshold 0.6 wires through to ReviewSession."""
        output_dir = tmp_path / "output"
        # Candidate at 0.7 — above 0.6 threshold, should be accepted
        candidate = _make_candidate("Matched", 0.7)

        with patch(
            "bookery.cli.commands.match_cmd._create_provider"
        ) as mock_provider_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = []
            mock_provider.search_by_title_author.return_value = [candidate]
            mock_provider_fn.return_value = mock_provider

            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "match", str(sample_epub), "-q",
                    "-t", "0.6", "-o", str(output_dir),
                ],
            )

        assert result.exit_code == 0
        assert "1 matched" in result.output

    def test_threshold_validation_rejects_out_of_range(self) -> None:
        """--threshold 1.5 is rejected by Click validation."""
        runner = CliRunner()
        result = runner.invoke(
            cli, ["match", ".", "-t", "1.5"],
        )
        assert result.exit_code != 0


class TestResumeOption:
    """Tests for --resume / --no-resume CLI option."""

    def test_resume_skips_existing_output(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        """File in output-dir is skipped when --resume is active."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        # Pre-create a file that matches the EPUB name
        (output_dir / sample_epub.name).write_text("already processed")

        candidate = _make_candidate("Matched", 0.95)

        with patch(
            "bookery.cli.commands.match_cmd._create_provider"
        ) as mock_provider_fn:
            mock_provider = MagicMock()
            mock_provider.search_by_isbn.return_value = [candidate]
            mock_provider_fn.return_value = mock_provider

            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "match", str(sample_epub), "-q",
                    "--resume", "-o", str(output_dir),
                ],
            )

        assert result.exit_code == 0
        # Should not have matched anything — it was skipped
        assert "matched" not in result.output or "0 matched" in result.output

    def test_resume_shows_skip_count(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        """Output contains 'Skipping N' when resume skips files."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / sample_epub.name).write_text("already processed")

        with patch(
            "bookery.cli.commands.match_cmd._create_provider"
        ) as mock_provider_fn:
            mock_provider_fn.return_value = MagicMock()

            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "match", str(sample_epub), "-q",
                    "--resume", "-o", str(output_dir),
                ],
            )

        assert result.exit_code == 0
        assert "kipping" in result.output and "1" in result.output

    def test_no_resume_processes_all(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        """--no-resume processes files even if output exists."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / sample_epub.name).write_text("already processed")

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
                [
                    "match", str(sample_epub), "-q",
                    "--no-resume", "-o", str(output_dir),
                ],
            )

        assert result.exit_code == 0
        assert "1 matched" in result.output

    def test_resume_handles_collision_suffixes(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        """A _1 suffix file counts as already processed."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        stem = sample_epub.stem
        # Only the collision suffix version exists
        (output_dir / f"{stem}_1.epub").write_text("collision copy")

        with patch(
            "bookery.cli.commands.match_cmd._create_provider"
        ) as mock_provider_fn:
            mock_provider_fn.return_value = MagicMock()

            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "match", str(sample_epub), "-q",
                    "--resume", "-o", str(output_dir),
                ],
            )

        assert result.exit_code == 0
        assert "kipping" in result.output

    def test_all_processed_shows_message(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        """When all files are skipped, a message is shown."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / sample_epub.name).write_text("done")

        with patch(
            "bookery.cli.commands.match_cmd._create_provider"
        ) as mock_provider_fn:
            mock_provider_fn.return_value = MagicMock()

            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "match", str(sample_epub), "-q",
                    "--resume", "-o", str(output_dir),
                ],
            )

        assert result.exit_code == 0
        assert "already processed" in result.output.lower()
