# ABOUTME: Unit tests for MOBI-to-EPUB conversion orchestration.
# ABOUTME: Tests convert_one() with mocked extraction for various scenarios.

from pathlib import Path
from unittest.mock import patch

import pytest

from bookery.core.converter import convert_one
from bookery.formats.mobi import MobiExtractResult, MobiReadError


@pytest.fixture
def _mock_epub_extraction(tmp_path: Path):
    """Set up a mock MOBI extraction that yields an EPUB file."""
    extract_dir = tmp_path / "mobi_tempdir"
    extract_dir.mkdir()
    epub_file = extract_dir / "mobi8" / "book.epub"
    epub_file.parent.mkdir(parents=True)

    # Create a minimal valid EPUB for metadata reading
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("test-id")
    book.set_title("Converted Book")
    book.set_language("en")
    book.add_author("Test Author")
    chapter = epub.EpubHtml(title="Ch1", file_name="ch1.xhtml", lang="en")
    chapter.content = b"<html><body><p>Content</p></body></html>"
    book.add_item(chapter)
    book.toc = [epub.Link("ch1.xhtml", "Ch1", "ch1")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]
    epub.write_epub(str(epub_file), book)

    return MobiExtractResult(
        tempdir=extract_dir,
        format="epub",
        epub_path=epub_file,
    )


@pytest.fixture
def _mock_html_extraction(tmp_path: Path):
    """Set up a mock MOBI extraction that yields an HTML file."""
    extract_dir = tmp_path / "mobi_tempdir"
    extract_dir.mkdir()
    html_file = extract_dir / "mobi7" / "book.html"
    html_file.parent.mkdir(parents=True)
    html_file.write_text(
        "<html><head><title>HTML Book</title></head>"
        "<body><h1>Chapter</h1><p>Content</p></body></html>"
    )

    return MobiExtractResult(
        tempdir=extract_dir,
        format="html",
        html_path=html_file,
    )


class TestConvertOneEpubPath:
    """Tests for convert_one() when extraction yields EPUB."""

    def test_happy_path(self, tmp_path: Path, _mock_epub_extraction) -> None:
        """Copies extracted EPUB to output directory."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")
        output_dir = tmp_path / "output"

        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.return_value = _mock_epub_extraction
            result = convert_one(mobi_file, output_dir)

        assert result.success is True
        assert result.epub_path is not None
        assert result.epub_path.exists()
        assert result.epub_path.parent == output_dir
        assert result.epub_path.suffix == ".epub"
        assert result.error is None

    def test_reads_metadata_from_result(self, tmp_path: Path, _mock_epub_extraction) -> None:
        """Populates metadata from the resulting EPUB."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")
        output_dir = tmp_path / "output"

        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.return_value = _mock_epub_extraction
            result = convert_one(mobi_file, output_dir)

        assert result.metadata is not None
        assert result.metadata.title == "Converted Book"

    def test_original_file_unchanged(self, tmp_path: Path, _mock_epub_extraction) -> None:
        """Original MOBI file is not modified."""
        mobi_file = tmp_path / "book.mobi"
        original_content = b"original mobi content"
        mobi_file.write_bytes(original_content)
        output_dir = tmp_path / "output"

        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.return_value = _mock_epub_extraction
            convert_one(mobi_file, output_dir)

        assert mobi_file.read_bytes() == original_content


class TestConvertOneHtmlPath:
    """Tests for convert_one() when extraction yields HTML."""

    def test_assembles_epub(self, tmp_path: Path, _mock_html_extraction) -> None:
        """Assembles an EPUB from extracted HTML."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")
        output_dir = tmp_path / "output"

        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.return_value = _mock_html_extraction
            result = convert_one(mobi_file, output_dir)

        assert result.success is True
        assert result.epub_path is not None
        assert result.epub_path.exists()
        assert result.epub_path.suffix == ".epub"


class TestConvertOneSkipAndForce:
    """Tests for skip-if-exists and --force behavior."""

    def test_skips_existing(self, tmp_path: Path, _mock_epub_extraction) -> None:
        """Skips conversion when output already exists and force=False."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        existing = output_dir / "book.epub"
        existing.write_bytes(b"already here")

        result = convert_one(mobi_file, output_dir, force=False)

        assert result.success is True
        assert result.skipped is True
        assert result.epub_path == existing
        # Content should be unchanged (not overwritten)
        assert existing.read_bytes() == b"already here"

    def test_normal_conversion_not_skipped(
        self, tmp_path: Path, _mock_epub_extraction,
    ) -> None:
        """Normal conversion sets skipped=False."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")
        output_dir = tmp_path / "output"

        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.return_value = _mock_epub_extraction
            result = convert_one(mobi_file, output_dir)

        assert result.success is True
        assert result.skipped is False

    def test_overwrites_with_force(self, tmp_path: Path, _mock_epub_extraction) -> None:
        """Overwrites existing output when force=True."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        existing = output_dir / "book.epub"
        existing.write_bytes(b"old content")

        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.return_value = _mock_epub_extraction
            result = convert_one(mobi_file, output_dir, force=True)

        assert result.success is True
        assert result.epub_path is not None
        # Content should be different now (overwritten)
        assert result.epub_path.read_bytes() != b"old content"


class TestConvertOneErrors:
    """Tests for convert_one() error handling."""

    def test_extraction_error(self, tmp_path: Path) -> None:
        """Returns error result when extraction fails."""
        mobi_file = tmp_path / "drm.mobi"
        mobi_file.write_bytes(b"drm content")
        output_dir = tmp_path / "output"

        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.side_effect = MobiReadError("DRM protected")
            result = convert_one(mobi_file, output_dir)

        assert result.success is False
        assert "DRM protected" in result.error
        assert result.epub_path is None

    def test_tempdir_cleaned_up_on_success(self, tmp_path: Path, _mock_epub_extraction) -> None:
        """Tempdir is cleaned up after successful conversion."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")
        output_dir = tmp_path / "output"
        tempdir = _mock_epub_extraction.tempdir

        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.return_value = _mock_epub_extraction
            convert_one(mobi_file, output_dir)

        assert not tempdir.exists()

    def test_tempdir_cleaned_up_on_error(self, tmp_path: Path) -> None:
        """Tempdir is cleaned up even after an error during assembly."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")
        output_dir = tmp_path / "output"

        extract_dir = tmp_path / "mobi_tempdir"
        extract_dir.mkdir()
        html_file = extract_dir / "book.html"
        html_file.write_text("")  # Empty HTML will cause issues

        bad_result = MobiExtractResult(
            tempdir=extract_dir,
            format="html",
            html_path=html_file,
        )

        with (
            patch("bookery.core.converter.extract_mobi") as mock_extract,
            patch("bookery.core.converter.assemble_epub_from_html") as mock_assemble,
        ):
            mock_extract.return_value = bad_result
            mock_assemble.side_effect = Exception("assembly failed")
            result = convert_one(mobi_file, output_dir)

        assert result.success is False
        assert not extract_dir.exists()
