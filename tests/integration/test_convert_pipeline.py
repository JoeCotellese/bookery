# ABOUTME: Integration tests for the MOBI-to-EPUB conversion pipeline.
# ABOUTME: Tests HTML-to-EPUB assembly with real ebooklib and convert+match chain.

from pathlib import Path
from unittest.mock import MagicMock, patch

from ebooklib import epub

from bookery.core.converter import convert_one
from bookery.core.pipeline import match_one
from bookery.formats.epub import read_epub_metadata
from bookery.formats.mobi import MobiExtractResult, assemble_epub_from_html
from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.types import BookMetadata


class TestHtmlToEpubAssembly:
    """Integration tests for HTML-to-EPUB assembly using real ebooklib."""

    def test_assembled_epub_is_readable(self, tmp_path: Path) -> None:
        """Assembled EPUB can be read back by ebooklib."""
        html_file = tmp_path / "book.html"
        html_file.write_text(
            "<html><head><title>Integration Test</title></head>"
            "<body><h1>Chapter 1</h1><p>Real content for integration test.</p></body></html>"
        )
        output = tmp_path / "assembled.epub"

        metadata = BookMetadata(
            title="Integration Test Book",
            authors=["Test Author"],
            language="en",
            publisher="Test Publisher",
        )

        assemble_epub_from_html(html_file, output, metadata=metadata)

        # Verify with real ebooklib read
        read_back = read_epub_metadata(output)
        assert read_back.title == "Integration Test Book"
        assert read_back.authors == ["Test Author"]
        assert read_back.language == "en"

    def test_assembled_epub_has_content(self, tmp_path: Path) -> None:
        """Assembled EPUB contains the original HTML content."""
        html_content = "<html><body><p>Specific test content ABC123</p></body></html>"
        html_file = tmp_path / "book.html"
        html_file.write_text(html_content)
        output = tmp_path / "assembled.epub"

        assemble_epub_from_html(html_file, output)

        # Read the EPUB and verify content exists
        book = epub.read_epub(str(output), options={"ignore_ncx": True})
        items = list(book.get_items())
        content_found = any(
            b"Specific test content ABC123" in item.get_content()
            for item in items
            if hasattr(item, "get_content")
        )
        assert content_found


class TestOpfMetadataRoundTrip:
    """Integration tests for OPF metadata flowing through assembly."""

    def test_opf_metadata_survives_assembly(self, tmp_path: Path) -> None:
        """Metadata from OPF is readable in the assembled EPUB."""
        from bookery.formats.mobi import parse_opf_metadata

        # Write a realistic OPF file
        opf_file = tmp_path / "content.opf"
        opf_file.write_text("""\
<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>The Martian</dc:title>
    <dc:creator>Andy Weir</dc:creator>
    <dc:language>en</dc:language>
    <dc:publisher>Crown Publishing</dc:publisher>
    <dc:identifier opf:scheme="ISBN">9780553418026</dc:identifier>
  </metadata>
</package>
""")
        metadata = parse_opf_metadata(opf_file)
        assert metadata is not None

        html_file = tmp_path / "book.html"
        html_file.write_text("<html><body><p>I'm stranded on Mars.</p></body></html>")
        output = tmp_path / "assembled.epub"

        assemble_epub_from_html(html_file, output, metadata=metadata)

        read_back = read_epub_metadata(output)
        assert read_back.title == "The Martian"
        assert read_back.authors == ["Andy Weir"]
        assert read_back.language == "en"

    def test_images_survive_assembly(self, tmp_path: Path) -> None:
        """Images from images_dir are readable in the assembled EPUB."""
        import ebooklib

        html_file = tmp_path / "book.html"
        html_file.write_text(
            '<html><body><img src="Images/photo.jpg"/></body></html>'
        )
        images_dir = tmp_path / "Images"
        images_dir.mkdir()
        image_data = b"\xff\xd8\xff\xe0" + b"\x00" * 100  # Fake JPEG
        (images_dir / "photo.jpg").write_bytes(image_data)

        output = tmp_path / "assembled.epub"
        assemble_epub_from_html(html_file, output, images_dir=images_dir)

        book = epub.read_epub(str(output), options={"ignore_ncx": True})
        image_items = [
            item for item in book.get_items()
            if item.get_type() == ebooklib.ITEM_IMAGE
        ]
        assert len(image_items) == 1
        assert image_items[0].get_content() == image_data

    def test_opf_metadata_and_images_together(self, tmp_path: Path) -> None:
        """Both OPF metadata and images survive assembly into EPUB."""
        import ebooklib

        from bookery.formats.mobi import parse_opf_metadata

        opf_file = tmp_path / "content.opf"
        opf_file.write_text("""\
<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Full Test</dc:title>
    <dc:creator>Test Author</dc:creator>
  </metadata>
</package>
""")
        metadata = parse_opf_metadata(opf_file)

        html_file = tmp_path / "book.html"
        html_file.write_text(
            '<html><body><img src="Images/fig1.png"/><p>Text</p></body></html>'
        )
        images_dir = tmp_path / "Images"
        images_dir.mkdir()
        (images_dir / "fig1.png").write_bytes(b"\x89PNG\r\n\x1a\nfake-png")

        output = tmp_path / "assembled.epub"
        assemble_epub_from_html(html_file, output, metadata=metadata, images_dir=images_dir)

        read_back = read_epub_metadata(output)
        assert read_back.title == "Full Test"
        assert read_back.authors == ["Test Author"]

        book = epub.read_epub(str(output), options={"ignore_ncx": True})
        image_items = [
            item for item in book.get_items()
            if item.get_type() == ebooklib.ITEM_IMAGE
        ]
        assert len(image_items) == 1


class TestNcxSplitRoundTrip:
    """Integration tests for NCX-based chapter splitting through full assembly."""

    def test_ncx_split_produces_multi_chapter_epub(self, tmp_path: Path) -> None:
        """Full round-trip: parse NCX → split HTML → assemble → readable multi-chapter EPUB."""
        import ebooklib

        from bookery.formats.mobi import (
            assemble_epub_from_html,
            parse_ncx_toc,
            split_html_by_anchors,
        )

        # Create a realistic NCX file
        ncx_file = tmp_path / "toc.ncx"
        ncx_file.write_text("""\
<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <navMap>
    <navPoint id="np1" playOrder="1">
      <navLabel><text>Chapter 1 - Arrival</text></navLabel>
      <content src="book.html#filepos000100"/>
    </navPoint>
    <navPoint id="np2" playOrder="2">
      <navLabel><text>Chapter 2 - Survival</text></navLabel>
      <content src="book.html#filepos000500"/>
    </navPoint>
    <navPoint id="np3" playOrder="3">
      <navLabel><text>Chapter 3 - Rescue</text></navLabel>
      <content src="book.html#filepos001000"/>
    </navPoint>
  </navMap>
</ncx>
""")

        # Create matching HTML with anchor points
        html_file = tmp_path / "book.html"
        html_file.write_text(
            '<html><body>'
            '<p>Book preamble</p>'
            '<a id="filepos000100"></a><h1>Chapter 1</h1>'
            '<p>Arrival on Mars. Content for chapter one.</p>'
            '<a id="filepos000500"></a><h1>Chapter 2</h1>'
            '<p>Learning to survive. Content for chapter two.</p>'
            '<a id="filepos001000"></a><h1>Chapter 3</h1>'
            '<p>Rescue mission. Content for chapter three.</p>'
            '</body></html>'
        )

        # Parse NCX
        nav_points = parse_ncx_toc(ncx_file)
        assert len(nav_points) == 3

        # Split HTML
        html_content = html_file.read_text()
        chapters = split_html_by_anchors(html_content, nav_points)
        assert len(chapters) == 3

        # Assemble EPUB
        output = tmp_path / "output.epub"
        metadata = BookMetadata(
            title="The Martian",
            authors=["Andy Weir"],
            language="en",
        )
        assemble_epub_from_html(
            html_file, output, metadata=metadata, chapters=chapters,
        )

        # Verify the EPUB
        assert output.exists()
        book = epub.read_epub(str(output), options={"ignore_ncx": True})

        # TOC has 3 entries
        assert len(book.toc) == 3
        toc_labels = [entry.title for entry in book.toc]
        assert "Chapter 1 - Arrival" in toc_labels
        assert "Chapter 2 - Survival" in toc_labels
        assert "Chapter 3 - Rescue" in toc_labels

        # Spine has 3 document items (plus nav)
        doc_items = [
            item for item in book.get_items()
            if item.get_type() == ebooklib.ITEM_DOCUMENT
        ]
        assert len(doc_items) >= 3

        # Content is present in each chapter
        all_content = b"".join(
            item.get_content() for item in doc_items
            if hasattr(item, "get_content")
        )
        assert b"Arrival on Mars" in all_content
        assert b"Learning to survive" in all_content
        assert b"Rescue mission" in all_content

        # Metadata survived
        read_back = read_epub_metadata(output)
        assert read_back.title == "The Martian"
        assert read_back.authors == ["Andy Weir"]

    def test_cover_page_is_first_spine_item(self, tmp_path: Path) -> None:
        """Converted EPUB with cover image has cover page as first spine item."""
        import xml.etree.ElementTree as ET
        import zipfile

        from bookery.formats.mobi import (
            assemble_epub_from_html,
            parse_ncx_toc,
            split_html_by_anchors,
        )

        ncx_file = tmp_path / "toc.ncx"
        ncx_file.write_text("""\
<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <navMap>
    <navPoint id="np1" playOrder="1">
      <navLabel><text>Chapter 1</text></navLabel>
      <content src="book.html#filepos000100"/>
    </navPoint>
  </navMap>
</ncx>
""")

        html_file = tmp_path / "book.html"
        html_file.write_text(
            '<html><body>'
            '<a id="filepos000100"></a><h1>Chapter 1</h1>'
            '<p>Content here.</p>'
            '</body></html>'
        )

        images_dir = tmp_path / "Images"
        images_dir.mkdir()
        (images_dir / "cover.jpg").write_bytes(b"\xff\xd8\xff\xe0fake-cover")

        nav_points = parse_ncx_toc(ncx_file)
        chapters = split_html_by_anchors(html_file.read_text(), nav_points)

        output = tmp_path / "output.epub"
        metadata = BookMetadata(title="Cover Test", authors=["Author"], language="en")
        assemble_epub_from_html(
            html_file, output, metadata=metadata, chapters=chapters,
            images_dir=images_dir,
        )

        # Parse the OPF spine and verify cover is first
        with zipfile.ZipFile(output) as z:
            opf = z.read("EPUB/content.opf").decode()

        root = ET.fromstring(opf)
        ns = {"opf": "http://www.idpf.org/2007/opf"}
        spine = root.find("opf:spine", ns)
        itemrefs = spine.findall("opf:itemref", ns)
        assert itemrefs[0].get("idref") == "cover", (
            "Expected cover as first spine item for Kobo rendering"
        )

    def test_ncx_split_with_images(self, tmp_path: Path) -> None:
        """NCX split EPUB includes images alongside chapters."""
        import ebooklib

        from bookery.formats.mobi import (
            assemble_epub_from_html,
            parse_ncx_toc,
            split_html_by_anchors,
        )

        ncx_file = tmp_path / "toc.ncx"
        ncx_file.write_text("""\
<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <navMap>
    <navPoint id="np1" playOrder="1">
      <navLabel><text>Chapter 1</text></navLabel>
      <content src="book.html#filepos000100"/>
    </navPoint>
  </navMap>
</ncx>
""")

        html_file = tmp_path / "book.html"
        html_file.write_text(
            '<html><body>'
            '<a id="filepos000100"></a><h1>Chapter 1</h1>'
            '<img src="Images/cover.jpg"/><p>Content</p>'
            '</body></html>'
        )

        images_dir = tmp_path / "Images"
        images_dir.mkdir()
        (images_dir / "cover.jpg").write_bytes(b"\xff\xd8\xff\xe0fake-jpg")

        nav_points = parse_ncx_toc(ncx_file)
        chapters = split_html_by_anchors(html_file.read_text(), nav_points)

        output = tmp_path / "output.epub"
        assemble_epub_from_html(
            html_file, output, chapters=chapters, images_dir=images_dir,
        )

        book = epub.read_epub(str(output), options={"ignore_ncx": True})
        cover_items = [
            item for item in book.get_items()
            if item.get_type() == ebooklib.ITEM_COVER
        ]
        assert len(cover_items) == 1
        assert cover_items[0].get_name() == "Images/cover.jpg"


class TestConvertThenMatchPipeline:
    """Integration tests for convert→match pipeline chain."""

    def test_converted_epub_flows_into_match(self, tmp_path: Path) -> None:
        """A converted EPUB can be passed to match_one() successfully."""
        # Set up a mock MOBI extraction that yields a valid EPUB
        extract_dir = tmp_path / "extract"
        extract_dir.mkdir()
        epub_file = extract_dir / "book.epub"

        book = epub.EpubBook()
        book.set_identifier("convert-match-test")
        book.set_title("Unconverted Title")
        book.set_language("en")
        book.add_author("Unknown")
        chapter = epub.EpubHtml(title="Ch1", file_name="ch1.xhtml", lang="en")
        chapter.content = b"<html><body><p>Content</p></body></html>"
        book.add_item(chapter)
        book.toc = [epub.Link("ch1.xhtml", "Ch1", "ch1")]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = ["nav", chapter]
        epub.write_epub(str(epub_file), book)

        mobi_file = tmp_path / "book.mobi"
        mobi_file.write_bytes(b"fake mobi")
        output_dir = tmp_path / "output"

        with patch("bookery.core.converter.extract_mobi") as mock_extract:
            mock_extract.return_value = MobiExtractResult(
                tempdir=extract_dir,
                format="epub",
                epub_path=epub_file,
            )
            convert_result = convert_one(mobi_file, output_dir)

        assert convert_result.success
        assert convert_result.epub_path.exists()

        # Now feed the converted EPUB into match_one with a mock provider
        candidate = MetadataCandidate(
            metadata=BookMetadata(
                title="The Real Title",
                authors=["Real Author"],
                language="en",
            ),
            confidence=0.95,
            source="test",
            source_id="test-1",
        )

        mock_provider = MagicMock()
        mock_provider.search_by_isbn.return_value = []
        mock_provider.search_by_title_author.return_value = [candidate]

        mock_review = MagicMock()
        mock_review.review.return_value = candidate.metadata

        match_result = match_one(convert_result.epub_path, mock_provider, mock_review, output_dir)

        assert match_result.status == "matched"
        assert match_result.metadata.title == "The Real Title"
