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
