# ABOUTME: End-to-end tests for the bookery convert CLI command.
# ABOUTME: Tests the full convert pipeline using CliRunner with mocked MOBI extraction.

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from ebooklib import epub

from bookery.cli import cli
from bookery.formats.mobi import MobiExtractResult, MobiReadError


def _make_valid_epub(path: Path, title: str = "Test Book", author: str = "Author") -> None:
    """Create a minimal valid EPUB at the given path."""
    book = epub.EpubBook()
    book.set_identifier("test-id")
    book.set_title(title)
    book.set_language("en")
    book.add_author(author)
    chapter = epub.EpubHtml(title="Ch1", file_name="ch1.xhtml", lang="en")
    chapter.content = b"<html><body><p>Content</p></body></html>"
    book.add_item(chapter)
    book.toc = [epub.Link("ch1.xhtml", "Ch1", "ch1")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]
    epub.write_epub(str(path), book)


def _mock_extract_to_epub(tmp_path: Path, epub_title: str = "Converted Book"):
    """Create a mock extract_mobi that returns a fresh EPUB result per call."""
    call_count = 0

    def side_effect(path):
        nonlocal call_count
        call_count += 1
        extract_dir = tmp_path / f"mobi_extract_{call_count}"
        extract_dir.mkdir(exist_ok=True)
        epub_file = extract_dir / "book.epub"
        _make_valid_epub(epub_file, title=epub_title)
        return MobiExtractResult(
            tempdir=extract_dir,
            format="epub",
            epub_path=epub_file,
        )

    return side_effect


class TestConvertCliSingleFile:
    """E2E tests for converting a single MOBI file."""

    def test_converts_single_file(self, tmp_path: Path) -> None:
        """Converts a single MOBI file and reports success."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")
        output_dir = tmp_path / "output"

        runner = CliRunner()
        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.side_effect = _mock_extract_to_epub(tmp_path)
            result = runner.invoke(cli, [
                "convert", str(mobi_file), "-o", str(output_dir),
            ])

        assert result.exit_code == 0, result.output
        assert "1 converted" in result.output
        assert (output_dir / "book.epub").exists()

    def test_no_mobi_files_message(self, tmp_path: Path) -> None:
        """Shows a message when no MOBI files are found."""
        not_mobi = tmp_path / "readme.txt"
        not_mobi.write_text("not a mobi")

        runner = CliRunner()
        result = runner.invoke(cli, ["convert", str(not_mobi)])

        assert result.exit_code == 0
        assert "No MOBI files found" in result.output


class TestConvertCliBatch:
    """E2E tests for converting a directory of MOBI files."""

    def test_converts_directory(self, tmp_path: Path) -> None:
        """Converts all MOBI files in a directory."""
        mobi_dir = tmp_path / "mobis"
        mobi_dir.mkdir()
        (mobi_dir / "book1.mobi").write_bytes(b"fake1")
        (mobi_dir / "book2.mobi").write_bytes(b"fake2")
        (mobi_dir / "readme.txt").write_text("ignore me")
        output_dir = tmp_path / "output"

        runner = CliRunner()
        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.side_effect = _mock_extract_to_epub(tmp_path)
            result = runner.invoke(cli, [
                "convert", str(mobi_dir), "-o", str(output_dir),
            ])

        assert result.exit_code == 0, result.output
        assert "2 converted" in result.output


class TestConvertCliForce:
    """E2E tests for --force flag."""

    def test_force_overwrites_existing(self, tmp_path: Path) -> None:
        """--force overwrites existing output files."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        existing = output_dir / "book.epub"
        existing.write_bytes(b"old content")

        runner = CliRunner()
        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.side_effect = _mock_extract_to_epub(tmp_path)
            result = runner.invoke(cli, [
                "convert", str(mobi_file), "-o", str(output_dir), "--force",
            ])

        assert result.exit_code == 0, result.output
        assert "1 converted" in result.output
        # File should be overwritten (different content)
        assert existing.read_bytes() != b"old content"


class TestConvertCliErrors:
    """E2E tests for error handling."""

    def test_error_output_for_corrupt_file(self, tmp_path: Path) -> None:
        """Shows error for corrupt/DRM MOBI files."""
        mobi_file = tmp_path / "drm.mobi"
        mobi_file.write_bytes(b"drm content")
        output_dir = tmp_path / "output"

        runner = CliRunner()
        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.side_effect = MobiReadError("DRM protected")
            result = runner.invoke(cli, [
                "convert", str(mobi_file), "-o", str(output_dir),
            ])

        assert result.exit_code == 0
        assert "1 error" in result.output

    def test_summary_counts(self, tmp_path: Path) -> None:
        """Summary shows correct counts for mixed results."""
        mobi_dir = tmp_path / "mobis"
        mobi_dir.mkdir()
        (mobi_dir / "good.mobi").write_bytes(b"good")
        (mobi_dir / "bad.mobi").write_bytes(b"bad")
        output_dir = tmp_path / "output"

        call_count = 0

        def mixed_extract(path):
            nonlocal call_count
            call_count += 1
            if "bad" in path.name:
                raise MobiReadError("corrupt file")
            return _mock_extract_to_epub(tmp_path)(path)

        runner = CliRunner()
        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.side_effect = mixed_extract
            result = runner.invoke(cli, [
                "convert", str(mobi_dir), "-o", str(output_dir),
            ])

        assert result.exit_code == 0, result.output
        assert "1 converted" in result.output
        assert "1 error" in result.output


class TestConvertCliMatch:
    """E2E tests for --match flag integration."""

    def test_match_flag_chains_into_match_pipeline(self, tmp_path: Path) -> None:
        """--match flag triggers match pipeline after conversion."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")
        output_dir = tmp_path / "output"

        runner = CliRunner()
        with (
            patch("bookery.core.converter.extract_mobi") as mock_extract,
            patch("bookery.cli.commands.convert_cmd._create_provider") as mock_provider_fn,
            patch("bookery.cli.commands.convert_cmd.match_one") as mock_match,
        ):
            mock_extract.side_effect = _mock_extract_to_epub(tmp_path)
            mock_provider = MagicMock()
            mock_provider_fn.return_value = mock_provider
            mock_match.return_value = MagicMock(
                status="matched", output_path=tmp_path / "out.epub",
            )
            result = runner.invoke(cli, [
                "convert", str(mobi_file), "-o", str(output_dir), "--match", "-q",
            ])

        assert result.exit_code == 0, result.output
        mock_match.assert_called_once()
