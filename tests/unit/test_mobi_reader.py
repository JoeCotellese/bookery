# ABOUTME: Unit tests for MOBI extraction and HTML-to-EPUB assembly.
# ABOUTME: Tests extract_mobi() and assemble_epub_from_html() with mocked mobi library.

from pathlib import Path
from unittest.mock import patch

import pytest

from bookery.formats.mobi import (
    MobiExtractResult,
    MobiReadError,
    extract_mobi,
    parse_opf_metadata,
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


class TestExtractMobiOpfAndImages:
    """Tests for opf_path and images_dir detection in extract_mobi()."""

    def test_detects_opf_in_mobi7(self, tmp_path: Path) -> None:
        """Populates opf_path when content.opf exists in mobi7/ directory."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")

        extract_dir = tmp_path / "extracted"
        mobi7_dir = extract_dir / "mobi7"
        mobi7_dir.mkdir(parents=True)
        html_file = mobi7_dir / "book.html"
        html_file.write_text("<html><body>Content</body></html>")
        opf_file = mobi7_dir / "content.opf"
        opf_file.write_text("<package/>")

        with patch("bookery.formats.mobi.mobi_extract") as mock_extract:
            mock_extract.return_value = (str(extract_dir), str(html_file))
            result = extract_mobi(mobi_file)

        assert result.opf_path == opf_file

    def test_detects_images_dir_in_mobi7(self, tmp_path: Path) -> None:
        """Populates images_dir when Images/ directory exists in mobi7/."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")

        extract_dir = tmp_path / "extracted"
        mobi7_dir = extract_dir / "mobi7"
        mobi7_dir.mkdir(parents=True)
        html_file = mobi7_dir / "book.html"
        html_file.write_text("<html><body>Content</body></html>")
        images_dir = mobi7_dir / "Images"
        images_dir.mkdir()
        (images_dir / "cover.jpg").write_bytes(b"\xff\xd8\xff\xe0")

        with patch("bookery.formats.mobi.mobi_extract") as mock_extract:
            mock_extract.return_value = (str(extract_dir), str(html_file))
            result = extract_mobi(mobi_file)

        assert result.images_dir == images_dir

    def test_no_opf_sets_none(self, tmp_path: Path) -> None:
        """Sets opf_path to None when no OPF file exists."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")

        extract_dir = tmp_path / "extracted"
        mobi7_dir = extract_dir / "mobi7"
        mobi7_dir.mkdir(parents=True)
        html_file = mobi7_dir / "book.html"
        html_file.write_text("<html><body>Content</body></html>")

        with patch("bookery.formats.mobi.mobi_extract") as mock_extract:
            mock_extract.return_value = (str(extract_dir), str(html_file))
            result = extract_mobi(mobi_file)

        assert result.opf_path is None

    def test_no_images_dir_sets_none(self, tmp_path: Path) -> None:
        """Sets images_dir to None when no Images/ directory exists."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")

        extract_dir = tmp_path / "extracted"
        mobi7_dir = extract_dir / "mobi7"
        mobi7_dir.mkdir(parents=True)
        html_file = mobi7_dir / "book.html"
        html_file.write_text("<html><body>Content</body></html>")

        with patch("bookery.formats.mobi.mobi_extract") as mock_extract:
            mock_extract.return_value = (str(extract_dir), str(html_file))
            result = extract_mobi(mobi_file)

        assert result.images_dir is None

    def test_epub_format_has_none_opf_and_images(self, tmp_path: Path) -> None:
        """EPUB extraction result has None for opf_path and images_dir."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")

        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        epub_file = extract_dir / "mobi8" / "book.epub"
        epub_file.parent.mkdir(parents=True)
        epub_file.write_bytes(b"fake epub")

        with patch("bookery.formats.mobi.mobi_extract") as mock_extract:
            mock_extract.return_value = (str(extract_dir), str(epub_file))
            result = extract_mobi(mobi_file)

        assert result.opf_path is None
        assert result.images_dir is None


class TestExtractMobiNcx:
    """Tests for toc.ncx detection in extract_mobi()."""

    def test_detects_ncx_in_mobi7(self, tmp_path: Path) -> None:
        """Populates ncx_path when toc.ncx exists alongside the HTML file."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")

        extract_dir = tmp_path / "extracted"
        mobi7_dir = extract_dir / "mobi7"
        mobi7_dir.mkdir(parents=True)
        html_file = mobi7_dir / "book.html"
        html_file.write_text("<html><body>Content</body></html>")
        ncx_file = mobi7_dir / "toc.ncx"
        ncx_file.write_text("<ncx/>")

        with patch("bookery.formats.mobi.mobi_extract") as mock_extract:
            mock_extract.return_value = (str(extract_dir), str(html_file))
            result = extract_mobi(mobi_file)

        assert result.ncx_path == ncx_file

    def test_no_ncx_sets_none(self, tmp_path: Path) -> None:
        """Sets ncx_path to None when no toc.ncx exists."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")

        extract_dir = tmp_path / "extracted"
        mobi7_dir = extract_dir / "mobi7"
        mobi7_dir.mkdir(parents=True)
        html_file = mobi7_dir / "book.html"
        html_file.write_text("<html><body>Content</body></html>")

        with patch("bookery.formats.mobi.mobi_extract") as mock_extract:
            mock_extract.return_value = (str(extract_dir), str(html_file))
            result = extract_mobi(mobi_file)

        assert result.ncx_path is None

    def test_epub_format_has_none_ncx(self, tmp_path: Path) -> None:
        """EPUB extraction result has None for ncx_path."""
        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")

        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        epub_file = extract_dir / "mobi8" / "book.epub"
        epub_file.parent.mkdir(parents=True)
        epub_file.write_bytes(b"fake epub")

        with patch("bookery.formats.mobi.mobi_extract") as mock_extract:
            mock_extract.return_value = (str(extract_dir), str(epub_file))
            result = extract_mobi(mobi_file)

        assert result.ncx_path is None


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


VALID_NCX = """\
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
    <navPoint id="np3" playOrder="3">
      <navLabel><text>Chapter 3</text></navLabel>
      <content src="book.html#filepos001000"/>
    </navPoint>
  </navMap>
</ncx>
"""


class TestParseNcxToc:
    """Tests for parse_ncx_toc()."""

    def test_parses_valid_ncx(self, tmp_path: Path) -> None:
        """Extracts chapter labels and anchor IDs from valid NCX."""
        from bookery.formats.mobi import parse_ncx_toc

        ncx_file = tmp_path / "toc.ncx"
        ncx_file.write_text(VALID_NCX)

        result = parse_ncx_toc(ncx_file)

        assert len(result) == 3
        assert result[0].label == "Chapter 1"
        assert result[0].anchor_id == "filepos000100"
        assert result[1].label == "Chapter 2"
        assert result[1].anchor_id == "filepos000500"
        assert result[2].label == "Chapter 3"
        assert result[2].anchor_id == "filepos001000"

    def test_strips_book_html_prefix(self, tmp_path: Path) -> None:
        """Strips 'book.html#' prefix from content src to get bare anchor ID."""
        from bookery.formats.mobi import parse_ncx_toc

        ncx = """\
<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <navMap>
    <navPoint id="np1" playOrder="1">
      <navLabel><text>Intro</text></navLabel>
      <content src="book.html#filepos000042"/>
    </navPoint>
  </navMap>
</ncx>
"""
        ncx_file = tmp_path / "toc.ncx"
        ncx_file.write_text(ncx)

        result = parse_ncx_toc(ncx_file)

        assert result[0].anchor_id == "filepos000042"

    def test_none_path_returns_empty(self) -> None:
        """Returns empty list when path is None."""
        from bookery.formats.mobi import parse_ncx_toc

        assert parse_ncx_toc(None) == []

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """Returns empty list when file doesn't exist."""
        from bookery.formats.mobi import parse_ncx_toc

        assert parse_ncx_toc(tmp_path / "nonexistent.ncx") == []

    def test_malformed_xml_returns_empty(self, tmp_path: Path) -> None:
        """Returns empty list for malformed XML, logs warning."""
        from bookery.formats.mobi import parse_ncx_toc

        ncx_file = tmp_path / "toc.ncx"
        ncx_file.write_text("<not valid xml <<>>")

        result = parse_ncx_toc(ncx_file)

        assert result == []

    def test_empty_navmap_returns_empty(self, tmp_path: Path) -> None:
        """Returns empty list when navMap has no navPoints."""
        from bookery.formats.mobi import parse_ncx_toc

        ncx = """\
<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <navMap>
  </navMap>
</ncx>
"""
        ncx_file = tmp_path / "toc.ncx"
        ncx_file.write_text(ncx)

        result = parse_ncx_toc(ncx_file)

        assert result == []

    def test_skips_navpoints_without_anchor(self, tmp_path: Path) -> None:
        """Skips navPoints whose content src has no fragment identifier."""
        from bookery.formats.mobi import parse_ncx_toc

        ncx = """\
<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <navMap>
    <navPoint id="np1" playOrder="1">
      <navLabel><text>Cover</text></navLabel>
      <content src="book.html"/>
    </navPoint>
    <navPoint id="np2" playOrder="2">
      <navLabel><text>Chapter 1</text></navLabel>
      <content src="book.html#filepos000100"/>
    </navPoint>
  </navMap>
</ncx>
"""
        ncx_file = tmp_path / "toc.ncx"
        ncx_file.write_text(ncx)

        result = parse_ncx_toc(ncx_file)

        assert len(result) == 1
        assert result[0].label == "Chapter 1"


class TestSplitHtmlByAnchors:
    """Tests for split_html_by_anchors()."""

    def test_splits_at_anchor_points(self) -> None:
        """Splits HTML at anchor points into separate chapters."""
        from bookery.formats.mobi import NcxNavPoint, split_html_by_anchors

        html = (
            '<html><body>'
            '<p>Preamble</p>'
            '<a id="filepos100"></a><h1>Chapter 1</h1><p>Content 1</p>'
            '<a id="filepos500"></a><h1>Chapter 2</h1><p>Content 2</p>'
            '</body></html>'
        )
        nav_points = [
            NcxNavPoint(label="Chapter 1", anchor_id="filepos100"),
            NcxNavPoint(label="Chapter 2", anchor_id="filepos500"),
        ]

        chapters = split_html_by_anchors(html, nav_points)

        assert len(chapters) == 2
        assert chapters[0].title == "Chapter 1"
        assert chapters[1].title == "Chapter 2"
        assert b"Content 1" in chapters[0].content
        assert b"Content 2" in chapters[1].content

    def test_content_before_first_anchor_prepended(self) -> None:
        """Content before the first anchor is prepended to the first chapter."""
        from bookery.formats.mobi import NcxNavPoint, split_html_by_anchors

        html = (
            '<html><body>'
            '<p>Preamble text</p>'
            '<a id="filepos100"></a><h1>Chapter 1</h1><p>Content 1</p>'
            '</body></html>'
        )
        nav_points = [
            NcxNavPoint(label="Chapter 1", anchor_id="filepos100"),
        ]

        chapters = split_html_by_anchors(html, nav_points)

        assert len(chapters) == 1
        assert b"Preamble text" in chapters[0].content
        assert b"Content 1" in chapters[0].content

    def test_strips_mbp_pagebreak(self) -> None:
        """Strips <mbp:pagebreak/> tags from chapter content."""
        from bookery.formats.mobi import NcxNavPoint, split_html_by_anchors

        html = (
            '<html><body>'
            '<a id="filepos100"></a><h1>Chapter 1</h1>'
            '<mbp:pagebreak/><p>After break</p>'
            '</body></html>'
        )
        nav_points = [
            NcxNavPoint(label="Chapter 1", anchor_id="filepos100"),
        ]

        chapters = split_html_by_anchors(html, nav_points)

        assert b"mbp:pagebreak" not in chapters[0].content
        assert b"After break" in chapters[0].content

    def test_produces_valid_xhtml_wrapping(self) -> None:
        """Each chapter is wrapped in valid XHTML boilerplate."""
        from bookery.formats.mobi import NcxNavPoint, split_html_by_anchors

        html = (
            '<html><body>'
            '<a id="filepos100"></a><h1>Chapter 1</h1><p>Content</p>'
            '</body></html>'
        )
        nav_points = [
            NcxNavPoint(label="Chapter 1", anchor_id="filepos100"),
        ]

        chapters = split_html_by_anchors(html, nav_points)

        content = chapters[0].content.decode("utf-8")
        assert "<html" in content
        assert "<body>" in content
        assert "</body>" in content
        assert "</html>" in content

    def test_anchor_not_found_returns_single_chapter(self) -> None:
        """Returns empty list when no anchors are found in the HTML."""
        from bookery.formats.mobi import NcxNavPoint, split_html_by_anchors

        html = "<html><body><p>No anchors here</p></body></html>"
        nav_points = [
            NcxNavPoint(label="Chapter 1", anchor_id="filepos999"),
        ]

        chapters = split_html_by_anchors(html, nav_points)

        assert chapters == []

    def test_empty_nav_points_returns_empty(self) -> None:
        """Returns empty list when nav_points is empty."""
        from bookery.formats.mobi import split_html_by_anchors

        html = "<html><body><p>Content</p></body></html>"

        chapters = split_html_by_anchors(html, [])

        assert chapters == []

    def test_file_names_are_sequential(self) -> None:
        """Chapter file names are ch001.xhtml, ch002.xhtml, etc."""
        from bookery.formats.mobi import NcxNavPoint, split_html_by_anchors

        html = (
            '<html><body>'
            '<a id="filepos100"></a><h1>Chapter 1</h1><p>C1</p>'
            '<a id="filepos500"></a><h1>Chapter 2</h1><p>C2</p>'
            '</body></html>'
        )
        nav_points = [
            NcxNavPoint(label="Chapter 1", anchor_id="filepos100"),
            NcxNavPoint(label="Chapter 2", anchor_id="filepos500"),
        ]

        chapters = split_html_by_anchors(html, nav_points)

        assert chapters[0].file_name == "ch001.xhtml"
        assert chapters[1].file_name == "ch002.xhtml"


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

    def test_includes_images_from_images_dir(self, tmp_path: Path) -> None:
        """Includes images from images_dir in the assembled EPUB."""
        import ebooklib
        from ebooklib import epub as epublib

        from bookery.formats.mobi import assemble_epub_from_html

        html_file = tmp_path / "book.html"
        html_file.write_text(
            '<html><body><img src="Images/photo.jpg"/></body></html>'
        )
        images_dir = tmp_path / "Images"
        images_dir.mkdir()
        # Minimal JPEG header (non-cover filename to test regular image path)
        (images_dir / "photo.jpg").write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")

        output = tmp_path / "output.epub"
        assemble_epub_from_html(html_file, output, images_dir=images_dir)

        # Read back and verify image item exists
        book = epublib.read_epub(str(output), options={"ignore_ncx": True})
        image_items = [
            item for item in book.get_items()
            if item.get_type() == ebooklib.ITEM_IMAGE
        ]
        assert len(image_items) == 1
        assert image_items[0].get_name() == "Images/photo.jpg"
        assert image_items[0].get_content() == b"\xff\xd8\xff\xe0fake-jpeg"

    def test_no_images_dir_produces_valid_epub(self, tmp_path: Path) -> None:
        """Produces a valid EPUB when images_dir is None."""
        from bookery.formats.mobi import assemble_epub_from_html

        html_file = tmp_path / "book.html"
        html_file.write_text("<html><body><p>No images</p></body></html>")
        output = tmp_path / "output.epub"

        result = assemble_epub_from_html(html_file, output, images_dir=None)

        assert result == output
        assert output.exists()

    def test_empty_images_dir_produces_valid_epub(self, tmp_path: Path) -> None:
        """Produces a valid EPUB when images_dir exists but is empty."""
        from bookery.formats.mobi import assemble_epub_from_html

        html_file = tmp_path / "book.html"
        html_file.write_text("<html><body><p>No images</p></body></html>")
        images_dir = tmp_path / "Images"
        images_dir.mkdir()
        output = tmp_path / "output.epub"

        result = assemble_epub_from_html(html_file, output, images_dir=images_dir)

        assert result == output
        assert output.exists()

    def test_multiple_images_included(self, tmp_path: Path) -> None:
        """Includes multiple images from images_dir."""
        import ebooklib
        from ebooklib import epub as epublib

        from bookery.formats.mobi import assemble_epub_from_html

        html_file = tmp_path / "book.html"
        html_file.write_text(
            '<html><body>'
            '<img src="Images/img1.jpg"/>'
            '<img src="Images/img2.png"/>'
            '</body></html>'
        )
        images_dir = tmp_path / "Images"
        images_dir.mkdir()
        (images_dir / "img1.jpg").write_bytes(b"\xff\xd8\xff\xe0jpeg-data")
        (images_dir / "img2.png").write_bytes(b"\x89PNG\r\n\x1a\npng-data")

        output = tmp_path / "output.epub"
        assemble_epub_from_html(html_file, output, images_dir=images_dir)

        book = epublib.read_epub(str(output), options={"ignore_ncx": True})
        image_items = [
            item for item in book.get_items()
            if item.get_type() == ebooklib.ITEM_IMAGE
        ]
        image_names = {item.get_name() for item in image_items}
        assert "Images/img1.jpg" in image_names
        assert "Images/img2.png" in image_names

    def test_multi_chapter_spine_and_toc(self, tmp_path: Path) -> None:
        """Creates EPUB with multiple spine items and TOC entries when chapters provided."""
        import ebooklib
        from ebooklib import epub as epublib

        from bookery.formats.mobi import Chapter, assemble_epub_from_html

        html_file = tmp_path / "book.html"
        html_file.write_text("<html><body><p>Unused</p></body></html>")
        output = tmp_path / "output.epub"

        chapters = [
            Chapter(
                title="Chapter 1",
                file_name="ch001.xhtml",
                content=b"<html><body><p>Content 1</p></body></html>",
            ),
            Chapter(
                title="Chapter 2",
                file_name="ch002.xhtml",
                content=b"<html><body><p>Content 2</p></body></html>",
            ),
            Chapter(
                title="Chapter 3",
                file_name="ch003.xhtml",
                content=b"<html><body><p>Content 3</p></body></html>",
            ),
        ]

        assemble_epub_from_html(html_file, output, chapters=chapters)

        book = epublib.read_epub(str(output), options={"ignore_ncx": True})
        # Spine should contain our 3 chapters (plus nav)
        doc_items = [
            item for item in book.get_items()
            if item.get_type() == ebooklib.ITEM_DOCUMENT
        ]
        doc_names = [item.get_name() for item in doc_items]
        assert "ch001.xhtml" in doc_names
        assert "ch002.xhtml" in doc_names
        assert "ch003.xhtml" in doc_names

        # TOC should have 3 entries
        assert len(book.toc) == 3

    def test_multi_chapter_preserves_content(self, tmp_path: Path) -> None:
        """Chapter content is preserved in multi-chapter EPUB."""
        from ebooklib import epub as epublib

        from bookery.formats.mobi import Chapter, assemble_epub_from_html

        html_file = tmp_path / "book.html"
        html_file.write_text("<html><body><p>Unused</p></body></html>")
        output = tmp_path / "output.epub"

        chapters = [
            Chapter(
                title="Ch1",
                file_name="ch001.xhtml",
                content=b"<html><body><p>UniqueMarkerABC</p></body></html>",
            ),
        ]

        assemble_epub_from_html(html_file, output, chapters=chapters)

        book = epublib.read_epub(str(output), options={"ignore_ncx": True})
        items = list(book.get_items())
        found = any(
            b"UniqueMarkerABC" in item.get_content()
            for item in items
            if hasattr(item, "get_content")
        )
        assert found

    def test_none_chapters_fallback(self, tmp_path: Path) -> None:
        """Falls back to single-chapter behavior when chapters is None."""
        from ebooklib import epub as epublib

        from bookery.formats.mobi import assemble_epub_from_html

        html_file = tmp_path / "book.html"
        html_file.write_text("<html><body><p>Single chapter</p></body></html>")
        output = tmp_path / "output.epub"

        assemble_epub_from_html(html_file, output, chapters=None)

        book = epublib.read_epub(str(output), options={"ignore_ncx": True})
        assert len(book.toc) == 1

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

    def test_cover_image_designated_in_metadata(self, tmp_path: Path) -> None:
        """Image with 'cover' in filename is designated as the EPUB cover."""
        import zipfile

        from bookery.formats.mobi import assemble_epub_from_html

        html_file = tmp_path / "book.html"
        html_file.write_text("<html><body><p>Test</p></body></html>")
        images_dir = tmp_path / "Images"
        images_dir.mkdir()
        cover_data = b"\xff\xd8\xff\xe0fake-cover-jpeg"
        (images_dir / "cover00183.jpeg").write_bytes(cover_data)
        (images_dir / "image00184.jpeg").write_bytes(b"\xff\xd8\xff\xe0other")

        output = tmp_path / "output.epub"
        assemble_epub_from_html(html_file, output, images_dir=images_dir)

        # Check raw OPF for cover metadata (ebooklib doesn't round-trip this)
        with zipfile.ZipFile(output) as z:
            opf = z.read("EPUB/content.opf").decode()

        assert 'name="cover"' in opf, "Expected OPF cover metadata"
        assert 'properties="cover-image"' in opf, "Expected cover-image property"
        assert "cover00183.jpeg" in opf, "Expected cover filename in OPF"

        # Cover page should be in the spine as the first item
        import xml.etree.ElementTree as ET

        root = ET.fromstring(opf)
        ns = {"opf": "http://www.idpf.org/2007/opf"}
        spine = root.find("opf:spine", ns)
        itemrefs = spine.findall("opf:itemref", ns)
        assert itemrefs[0].get("idref") == "cover", (
            "Expected cover as first spine item"
        )

    def test_cover_page_has_fullscreen_styling(self, tmp_path: Path) -> None:
        """Cover page XHTML uses viewport-filling CSS for e-reader compatibility."""
        import zipfile

        from bookery.formats.mobi import assemble_epub_from_html

        html_file = tmp_path / "book.html"
        html_file.write_text("<html><body><p>Test</p></body></html>")
        images_dir = tmp_path / "Images"
        images_dir.mkdir()
        (images_dir / "cover.jpg").write_bytes(b"\xff\xd8\xff\xe0fake-cover")

        output = tmp_path / "output.epub"
        assemble_epub_from_html(html_file, output, images_dir=images_dir)

        with zipfile.ZipFile(output) as z:
            cover_xhtml = z.read("EPUB/cover.xhtml").decode()
            cover_css = z.read("EPUB/style/cover.css").decode()

        # Inline styles on the img tag (preserved by lxml)
        assert "width:100%" in cover_xhtml, "Cover img should have width:100%"
        assert "height:100%" in cover_xhtml, "Cover img should have height:100%"
        assert "object-fit:contain" in cover_xhtml, (
            "Cover img should use object-fit:contain"
        )
        # Linked external CSS for belt-and-suspenders e-reader support
        assert "cover.css" in cover_xhtml, "Cover should link to cover.css"
        assert "object-fit" in cover_css, "Cover CSS should contain object-fit"

    def test_cover_image_not_set_when_no_cover_filename(self, tmp_path: Path) -> None:
        """No cover metadata when no image has 'cover' in the filename."""
        import zipfile

        from bookery.formats.mobi import assemble_epub_from_html

        html_file = tmp_path / "book.html"
        html_file.write_text("<html><body><p>Test</p></body></html>")
        images_dir = tmp_path / "Images"
        images_dir.mkdir()
        (images_dir / "image001.jpeg").write_bytes(b"\xff\xd8\xff\xe0data")

        output = tmp_path / "output.epub"
        assemble_epub_from_html(html_file, output, images_dir=images_dir)

        with zipfile.ZipFile(output) as z:
            opf = z.read("EPUB/content.opf").decode()

        assert 'name="cover"' not in opf, "Should not set cover metadata"

    def test_no_cover_not_in_spine(self, tmp_path: Path) -> None:
        """Cover page is NOT in the spine when no cover image exists."""
        import xml.etree.ElementTree as ET
        import zipfile

        from bookery.formats.mobi import assemble_epub_from_html

        html_file = tmp_path / "book.html"
        html_file.write_text("<html><body><p>Test</p></body></html>")

        output = tmp_path / "output.epub"
        assemble_epub_from_html(html_file, output, images_dir=None)

        with zipfile.ZipFile(output) as z:
            opf = z.read("EPUB/content.opf").decode()

        root = ET.fromstring(opf)
        ns = {"opf": "http://www.idpf.org/2007/opf"}
        spine = root.find("opf:spine", ns)
        idrefs = [ref.get("idref") for ref in spine.findall("opf:itemref", ns)]
        assert "cover" not in idrefs, "Cover should not be in spine without cover image"


# Helper: minimal valid OPF content for tests
VALID_OPF = """\
<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>The Martian</dc:title>
    <dc:creator>Andy Weir</dc:creator>
    <dc:language>en</dc:language>
    <dc:publisher>Crown Publishing</dc:publisher>
    <dc:description>A novel about survival on Mars.</dc:description>
    <dc:identifier opf:scheme="ISBN">9780553418026</dc:identifier>
  </metadata>
</package>
"""


class TestParseOpfMetadata:
    """Tests for parse_opf_metadata()."""

    def test_parses_valid_opf(self, tmp_path: Path) -> None:
        """Extracts title, author, language, publisher, description, ISBN from a valid OPF."""
        opf_file = tmp_path / "content.opf"
        opf_file.write_text(VALID_OPF)

        result = parse_opf_metadata(opf_file)

        assert result is not None
        assert result.title == "The Martian"
        assert result.authors == ["Andy Weir"]
        assert result.language == "en"
        assert result.publisher == "Crown Publishing"
        assert result.description == "A novel about survival on Mars."
        assert result.isbn == "9780553418026"

    def test_multiple_authors(self, tmp_path: Path) -> None:
        """Parses multiple dc:creator elements into authors list."""
        opf = """\
<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Good Omens</dc:title>
    <dc:creator>Terry Pratchett</dc:creator>
    <dc:creator>Neil Gaiman</dc:creator>
  </metadata>
</package>
"""
        opf_file = tmp_path / "content.opf"
        opf_file.write_text(opf)

        result = parse_opf_metadata(opf_file)

        assert result is not None
        assert result.authors == ["Terry Pratchett", "Neil Gaiman"]

    def test_isbn_from_identifier(self, tmp_path: Path) -> None:
        """Extracts ISBN from dc:identifier with opf:scheme='ISBN'."""
        opf = """\
<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>Test Book</dc:title>
    <dc:identifier opf:scheme="ISBN">978-0-13-468599-1</dc:identifier>
    <dc:identifier opf:scheme="ASIN">B00ABC1234</dc:identifier>
  </metadata>
</package>
"""
        opf_file = tmp_path / "content.opf"
        opf_file.write_text(opf)

        result = parse_opf_metadata(opf_file)

        assert result is not None
        assert result.isbn == "978-0-13-468599-1"

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        """Returns None when the OPF file doesn't exist."""
        missing = tmp_path / "nonexistent.opf"
        result = parse_opf_metadata(missing)
        assert result is None

    def test_none_path_returns_none(self) -> None:
        """Returns None when path is None."""
        result = parse_opf_metadata(None)
        assert result is None

    def test_malformed_xml_returns_none(self, tmp_path: Path) -> None:
        """Returns None for malformed XML without crashing."""
        opf_file = tmp_path / "content.opf"
        opf_file.write_text("<not valid xml <<>>")

        result = parse_opf_metadata(opf_file)

        assert result is None

    def test_empty_title_returns_none(self, tmp_path: Path) -> None:
        """Returns None when dc:title is empty."""
        opf = """\
<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title></dc:title>
  </metadata>
</package>
"""
        opf_file = tmp_path / "content.opf"
        opf_file.write_text(opf)

        result = parse_opf_metadata(opf_file)

        assert result is None

    def test_missing_title_returns_none(self, tmp_path: Path) -> None:
        """Returns None when no dc:title element exists."""
        opf = """\
<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:creator>Author Only</dc:creator>
  </metadata>
</package>
"""
        opf_file = tmp_path / "content.opf"
        opf_file.write_text(opf)

        result = parse_opf_metadata(opf_file)

        assert result is None

    def test_missing_optional_fields(self, tmp_path: Path) -> None:
        """Parses successfully when only title is present; optional fields default."""
        opf = """\
<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Minimal Book</dc:title>
  </metadata>
</package>
"""
        opf_file = tmp_path / "content.opf"
        opf_file.write_text(opf)

        result = parse_opf_metadata(opf_file)

        assert result is not None
        assert result.title == "Minimal Book"
        assert result.authors == []
        assert result.language is None
        assert result.publisher is None
        assert result.isbn is None
        assert result.description is None
