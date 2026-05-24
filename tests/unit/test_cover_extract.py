# ABOUTME: Unit tests for the cover extractor used by the web cover route.
# ABOUTME: Covers EPUB-with-cover, EPUB-without-cover, and content-type detection.

from pathlib import Path

import pytest
from ebooklib import epub

from bookery.formats.epub import extract_cover_bytes


def _make_epub_with_cover(path: Path, image_bytes: bytes, media_type: str = "image/jpeg") -> Path:
    """Build a minimal EPUB carrying a designated cover image."""
    book = epub.EpubBook()
    book.set_identifier("cover-fixture-id")
    book.set_title("Cover Fixture")
    book.set_language("en")
    book.add_author("Test Author")

    # set_cover wires the cover-image manifest entry and the OPF meta
    # name="cover" tag — the convention extract_cover_bytes searches for.
    book.set_cover("cover.jpg" if media_type == "image/jpeg" else "cover.png", image_bytes)

    chapter = epub.EpubHtml(title="Chapter 1", file_name="chap01.xhtml", lang="en")
    chapter.content = b"<html><body><p>x</p></body></html>"
    book.add_item(chapter)
    book.toc = [epub.Link("chap01.xhtml", "Chapter 1", "chap01")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]

    epub.write_epub(str(path), book)
    return path


@pytest.fixture
def epub_with_cover(tmp_path: Path) -> Path:
    """EPUB with a designated cover image (JPEG bytes)."""
    # Fake JPEG bytes — magic header is enough; we never decode the image.
    jpeg = b"\xff\xd8\xff\xe0" + b"bookery-cover-fixture" * 4
    return _make_epub_with_cover(tmp_path / "with_cover.epub", jpeg)


@pytest.fixture
def epub_without_cover(tmp_path: Path) -> Path:
    """EPUB with no cover image declared."""
    book = epub.EpubBook()
    book.set_identifier("no-cover-id")
    book.set_title("No Cover")
    book.set_language("en")
    book.add_author("Test Author")

    chapter = epub.EpubHtml(title="Chapter 1", file_name="chap01.xhtml", lang="en")
    chapter.content = b"<html><body><p>x</p></body></html>"
    book.add_item(chapter)
    book.toc = [epub.Link("chap01.xhtml", "Chapter 1", "chap01")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]

    path = tmp_path / "no_cover.epub"
    epub.write_epub(str(path), book)
    return path


class TestExtractCoverBytes:
    def test_returns_bytes_and_content_type_for_epub_with_cover(
        self, epub_with_cover: Path
    ) -> None:
        result = extract_cover_bytes(epub_with_cover)
        assert result is not None
        data, content_type = result
        assert isinstance(data, bytes)
        assert len(data) > 0
        # JPEG magic bytes survive the round-trip.
        assert data.startswith(b"\xff\xd8\xff")
        assert content_type == "image/jpeg"

    def test_returns_none_for_epub_without_cover(self, epub_without_cover: Path) -> None:
        assert extract_cover_bytes(epub_without_cover) is None

    def test_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        assert extract_cover_bytes(tmp_path / "does_not_exist.epub") is None

    def test_returns_none_for_non_epub_file(self, tmp_path: Path) -> None:
        bad = tmp_path / "not_an_epub.epub"
        bad.write_text("not actually an epub")
        assert extract_cover_bytes(bad) is None

    def test_detects_png_content_type(self, tmp_path: Path) -> None:
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"bookery-png" * 4
        path = _make_epub_with_cover(
            tmp_path / "png_cover.epub", png_bytes, media_type="image/png"
        )
        result = extract_cover_bytes(path)
        assert result is not None
        data, content_type = result
        assert data.startswith(b"\x89PNG")
        assert content_type == "image/png"
