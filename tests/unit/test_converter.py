# ABOUTME: Unit tests for MOBI-to-EPUB conversion orchestration.
# ABOUTME: Tests convert_one() with mocked extraction for various scenarios.

from pathlib import Path
from unittest.mock import patch

import pytest

from bookery.core.converter import convert_one
from bookery.core.pathformat import record_processed
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
        # EPUB is organized under output_dir in author/title structure
        assert str(result.epub_path).startswith(str(output_dir))
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

    def test_passes_opf_metadata_to_assembly(self, tmp_path: Path) -> None:
        """Parses OPF metadata and passes it to assemble_epub_from_html()."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")
        output_dir = tmp_path / "output"

        extract_dir = tmp_path / "mobi_tempdir"
        mobi7_dir = extract_dir / "mobi7"
        mobi7_dir.mkdir(parents=True)
        html_file = mobi7_dir / "book.html"
        html_file.write_text("<html><body><p>Content</p></body></html>")
        opf_file = mobi7_dir / "content.opf"
        opf_file.write_text("""\
<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>The Martian</dc:title>
    <dc:creator>Andy Weir</dc:creator>
    <dc:language>en</dc:language>
  </metadata>
</package>
""")

        extraction = MobiExtractResult(
            tempdir=extract_dir,
            format="html",
            html_path=html_file,
            opf_path=opf_file,
        )

        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.return_value = extraction
            result = convert_one(mobi_file, output_dir)

        assert result.success is True
        assert result.metadata is not None
        assert result.metadata.title == "The Martian"
        assert "Andy Weir" in result.metadata.authors

    def test_passes_images_dir_to_assembly(self, tmp_path: Path) -> None:
        """Passes images_dir from extract result to assemble_epub_from_html()."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")
        output_dir = tmp_path / "output"

        extract_dir = tmp_path / "mobi_tempdir"
        mobi7_dir = extract_dir / "mobi7"
        mobi7_dir.mkdir(parents=True)
        html_file = mobi7_dir / "book.html"
        html_file.write_text(
            '<html><body><img src="Images/cover.jpg"/></body></html>'
        )
        images_dir = mobi7_dir / "Images"
        images_dir.mkdir()
        (images_dir / "cover.jpg").write_bytes(b"\xff\xd8\xff\xe0fake-jpg")

        extraction = MobiExtractResult(
            tempdir=extract_dir,
            format="html",
            html_path=html_file,
            images_dir=images_dir,
        )

        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.return_value = extraction
            result = convert_one(mobi_file, output_dir)

        assert result.success is True

        # Verify the EPUB actually contains the image
        import ebooklib
        from ebooklib import epub

        book = epub.read_epub(str(result.epub_path), options={"ignore_ncx": True})
        cover_items = [
            item for item in book.get_items()
            if item.get_type() == ebooklib.ITEM_COVER
        ]
        assert len(cover_items) == 1
        assert cover_items[0].get_name() == "Images/cover.jpg"

    def test_ncx_chapters_passed_to_assembly(self, tmp_path: Path) -> None:
        """Parses NCX and splits HTML into chapters when NCX is available."""
        import ebooklib
        from ebooklib import epub

        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")
        output_dir = tmp_path / "output"

        extract_dir = tmp_path / "mobi_tempdir"
        mobi7_dir = extract_dir / "mobi7"
        mobi7_dir.mkdir(parents=True)
        html_file = mobi7_dir / "book.html"
        html_file.write_text(
            '<html><body>'
            '<a id="filepos000100"></a><h1>Chapter 1</h1><p>Content one</p>'
            '<a id="filepos000500"></a><h1>Chapter 2</h1><p>Content two</p>'
            '</body></html>'
        )
        ncx_file = mobi7_dir / "toc.ncx"
        ncx_file.write_text("""\
<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <navMap>
    <navPoint id="np1" playOrder="1">
      <navLabel><text>Chapter 1</text></navLabel>
      <content src="book.html#filepos000100"/>
    </navPoint>
    <navPoint id="np2" playOrder="2">
      <navLabel><text>Chapter 2</text></navLabel>
      <content src="book.html#filepos000500"/>
    </navPoint>
  </navMap>
</ncx>
""")

        extraction = MobiExtractResult(
            tempdir=extract_dir,
            format="html",
            html_path=html_file,
            ncx_path=ncx_file,
        )

        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.return_value = extraction
            result = convert_one(mobi_file, output_dir)

        assert result.success is True
        assert result.epub_path is not None

        # Verify the EPUB has 2 chapters in the TOC
        book = epub.read_epub(str(result.epub_path), options={"ignore_ncx": True})
        assert len(book.toc) == 2

        # Verify chapter content is present
        doc_items = [
            item for item in book.get_items()
            if item.get_type() == ebooklib.ITEM_DOCUMENT
        ]
        doc_names = [item.get_name() for item in doc_items]
        assert "ch001.xhtml" in doc_names
        assert "ch002.xhtml" in doc_names

    def test_no_ncx_falls_back_to_single_chapter(self, tmp_path: Path) -> None:
        """Falls back to single-chapter when no NCX is present."""
        from ebooklib import epub

        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")
        output_dir = tmp_path / "output"

        extract_dir = tmp_path / "mobi_tempdir"
        mobi7_dir = extract_dir / "mobi7"
        mobi7_dir.mkdir(parents=True)
        html_file = mobi7_dir / "book.html"
        html_file.write_text("<html><body><p>Content</p></body></html>")

        extraction = MobiExtractResult(
            tempdir=extract_dir,
            format="html",
            html_path=html_file,
            ncx_path=None,
        )

        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.return_value = extraction
            result = convert_one(mobi_file, output_dir)

        assert result.success is True
        book = epub.read_epub(str(result.epub_path), options={"ignore_ncx": True})
        assert len(book.toc) == 1

    def test_missing_opf_falls_back_to_filename(self, tmp_path: Path) -> None:
        """Uses filename as title when no OPF is available."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")
        output_dir = tmp_path / "output"

        extract_dir = tmp_path / "mobi_tempdir"
        mobi7_dir = extract_dir / "mobi7"
        mobi7_dir.mkdir(parents=True)
        html_file = mobi7_dir / "book.html"
        html_file.write_text("<html><body><p>Content</p></body></html>")

        extraction = MobiExtractResult(
            tempdir=extract_dir,
            format="html",
            html_path=html_file,
            opf_path=None,
            images_dir=None,
        )

        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.return_value = extraction
            result = convert_one(mobi_file, output_dir)

        assert result.success is True
        assert result.metadata is not None
        assert result.metadata.title == "book"


class TestConvertOneSkipAndForce:
    """Tests for skip-if-exists and --force behavior."""

    def test_skips_existing(self, tmp_path: Path, _mock_epub_extraction) -> None:
        """Skips conversion when source is recorded in manifest."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        # Record as already processed via manifest
        record_processed(output_dir, "book.mobi")

        result = convert_one(mobi_file, output_dir, force=False)

        assert result.success is True
        assert result.skipped is True

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
        """Force converts even when output exists in organized location."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.return_value = _mock_epub_extraction
            result = convert_one(mobi_file, output_dir, force=True)

        assert result.success is True
        assert result.epub_path is not None
        assert result.epub_path.exists()
        # EPUB should be in organized subdirectory
        assert str(result.epub_path).startswith(str(output_dir))


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
