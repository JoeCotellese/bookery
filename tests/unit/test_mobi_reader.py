# ABOUTME: Unit tests for MOBI extraction and HTML-to-EPUB assembly.
# ABOUTME: Tests extract_mobi() and assemble_epub_from_html() with mocked mobi library.

from pathlib import Path
from unittest.mock import patch

import pytest

from bookery.formats.mobi import (
    MobiExtractResult,
    MobiReadError,
    extract_mobi,
)


class TestExtractMobiEpubPath:
    """Tests for extract_mobi() when the mobi library extracts to EPUB."""

    def test_returns_epub_result(self, tmp_path: Path) -> None:
        """Returns MobiExtractResult with format='epub' when EPUB is extracted."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")

        # Simulate mobi.extract() output: tempdir with an EPUB file
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        epub_file = extract_dir / "mobi8" / "book.epub"
        epub_file.parent.mkdir(parents=True)
        epub_file.write_bytes(b"fake epub content")

        with patch("bookery.formats.mobi.mobi_extract") as mock_extract:
            mock_extract.return_value = (str(extract_dir), str(epub_file))
            result = extract_mobi(mobi_file)

        assert isinstance(result, MobiExtractResult)
        assert result.format == "epub"
        assert result.epub_path == epub_file
        assert result.html_path is None
        assert result.tempdir == extract_dir

    def test_returns_html_result(self, tmp_path: Path) -> None:
        """Returns MobiExtractResult with format='html' when only HTML is extracted."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")

        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        html_file = extract_dir / "mobi7" / "book.html"
        html_file.parent.mkdir(parents=True)
        html_file.write_text("<html><body><p>Content</p></body></html>")

        with patch("bookery.formats.mobi.mobi_extract") as mock_extract:
            mock_extract.return_value = (str(extract_dir), str(html_file))
            result = extract_mobi(mobi_file)

        assert isinstance(result, MobiExtractResult)
        assert result.format == "html"
        assert result.html_path == html_file
        assert result.epub_path is None
        assert result.tempdir == extract_dir


class TestExtractMobiErrors:
    """Tests for extract_mobi() error handling."""

    def test_file_not_found(self, tmp_path: Path) -> None:
        """Raises MobiReadError for a nonexistent file."""
        missing = tmp_path / "nonexistent.mobi"
        with pytest.raises(MobiReadError, match="File not found"):
            extract_mobi(missing)

    def test_mobi_extract_raises(self, tmp_path: Path) -> None:
        """Raises MobiReadError when mobi.extract() raises ValueError (e.g. DRM)."""
        mobi_file = tmp_path / "drm.mobi"
        mobi_file.write_bytes(b"fake drm mobi")

        with patch("bookery.formats.mobi.mobi_extract") as mock_extract:
            mock_extract.side_effect = ValueError("DRM protected")
            with pytest.raises(MobiReadError, match="DRM protected"):
                extract_mobi(mobi_file)

    def test_mobi_extract_generic_exception(self, tmp_path: Path) -> None:
        """Raises MobiReadError when mobi.extract() raises any exception."""
        mobi_file = tmp_path / "bad.mobi"
        mobi_file.write_bytes(b"corrupt")

        with patch("bookery.formats.mobi.mobi_extract") as mock_extract:
            mock_extract.side_effect = Exception("corrupt file")
            with pytest.raises(MobiReadError, match="corrupt file"):
                extract_mobi(mobi_file)


class TestAssembleEpubFromHtml:
    """Tests for assemble_epub_from_html()."""

    def test_produces_valid_epub(self, tmp_path: Path) -> None:
        """Creates a valid EPUB file from an HTML file."""
        from bookery.formats.mobi import assemble_epub_from_html

        html_file = tmp_path / "book.html"
        html_file.write_text(
            "<html><head><title>Test Book</title></head>"
            "<body><h1>Chapter 1</h1><p>Some content here.</p></body></html>"
        )
        output = tmp_path / "output.epub"

        result = assemble_epub_from_html(html_file, output)

        assert result == output
        assert output.exists()
        assert output.stat().st_size > 0

    def test_preserves_metadata(self, tmp_path: Path) -> None:
        """Preserves provided BookMetadata in the assembled EPUB."""
        from bookery.formats.epub import read_epub_metadata
        from bookery.formats.mobi import assemble_epub_from_html
        from bookery.metadata.types import BookMetadata

        html_file = tmp_path / "book.html"
        html_file.write_text("<html><body><p>Content</p></body></html>")
        output = tmp_path / "output.epub"

        metadata = BookMetadata(
            title="Dune",
            authors=["Frank Herbert"],
            language="en",
        )

        assemble_epub_from_html(html_file, output, metadata=metadata)

        read_back = read_epub_metadata(output)
        assert read_back.title == "Dune"
        assert read_back.authors == ["Frank Herbert"]
        assert read_back.language == "en"

    def test_uses_filename_as_title_when_no_metadata(self, tmp_path: Path) -> None:
        """Uses the HTML filename stem as the EPUB title when no metadata is given."""
        from bookery.formats.epub import read_epub_metadata
        from bookery.formats.mobi import assemble_epub_from_html

        html_file = tmp_path / "My Great Book.html"
        html_file.write_text("<html><body><p>Content</p></body></html>")
        output = tmp_path / "output.epub"

        assemble_epub_from_html(html_file, output)

        read_back = read_epub_metadata(output)
        assert read_back.title == "My Great Book"
