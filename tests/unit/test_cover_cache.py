# ABOUTME: Unit tests for the on-disk cover cache used by the web cover route.
# ABOUTME: Verifies cache hits, misses, and the placeholder fallback for missing covers.

from pathlib import Path

import pytest
from ebooklib import epub

from bookery.web.covers import (
    PLACEHOLDER_CONTENT_TYPE,
    PLACEHOLDER_SVG,
    get_or_extract_cover,
    invalidate_cover,
)


def _epub_with_cover(path: Path) -> Path:
    book = epub.EpubBook()
    book.set_identifier("cache-fixture-id")
    book.set_title("Cache Fixture")
    book.set_language("en")
    book.add_author("Test Author")

    jpeg = b"\xff\xd8\xff\xe0" + b"cache-fixture-jpeg" * 4
    book.set_cover("cover.jpg", jpeg)

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
def epub_path(tmp_path: Path) -> Path:
    return _epub_with_cover(tmp_path / "fixture.epub")


class TestGetOrExtractCover:
    def test_extracts_and_caches_on_first_call(self, tmp_path: Path, epub_path: Path) -> None:
        library_root = tmp_path / "library"
        library_root.mkdir()

        data, content_type = get_or_extract_cover(
            book_id=42, epub_path=epub_path, library_root=library_root
        )

        assert content_type == "image/jpeg"
        assert data.startswith(b"\xff\xd8\xff")
        # Cache file should have been written under .covers/.
        cached = library_root / ".covers" / "42.jpg"
        assert cached.exists()
        assert cached.read_bytes() == data

    def test_returns_cached_bytes_on_second_call(self, tmp_path: Path, epub_path: Path) -> None:
        library_root = tmp_path / "library"
        library_root.mkdir()

        get_or_extract_cover(book_id=7, epub_path=epub_path, library_root=library_root)

        # Replace the cached file with sentinel bytes to prove the second
        # call serves from disk and does not re-extract.
        cached = library_root / ".covers" / "7.jpg"
        sentinel = b"cached-sentinel-bytes"
        cached.write_bytes(sentinel)

        data, content_type = get_or_extract_cover(
            book_id=7, epub_path=epub_path, library_root=library_root
        )
        assert data == sentinel
        assert content_type == "image/jpeg"

    def test_returns_placeholder_when_epub_has_no_cover(self, tmp_path: Path) -> None:
        # Build an EPUB with no cover.
        book = epub.EpubBook()
        book.set_identifier("no-cover")
        book.set_title("No Cover")
        book.set_language("en")
        book.add_author("Anon")
        chapter = epub.EpubHtml(title="c", file_name="c.xhtml", lang="en")
        chapter.content = b"<html><body><p>x</p></body></html>"
        book.add_item(chapter)
        book.toc = [epub.Link("c.xhtml", "c", "c")]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = ["nav", chapter]
        epub_path = tmp_path / "blank.epub"
        epub.write_epub(str(epub_path), book)

        library_root = tmp_path / "library"
        library_root.mkdir()

        data, content_type = get_or_extract_cover(
            book_id=1, epub_path=epub_path, library_root=library_root
        )
        assert data == PLACEHOLDER_SVG
        assert content_type == PLACEHOLDER_CONTENT_TYPE

    def test_returns_placeholder_when_epub_path_is_none(self, tmp_path: Path) -> None:
        library_root = tmp_path / "library"
        library_root.mkdir()

        data, content_type = get_or_extract_cover(
            book_id=1, epub_path=None, library_root=library_root
        )
        assert data == PLACEHOLDER_SVG
        assert content_type == PLACEHOLDER_CONTENT_TYPE

    def test_returns_placeholder_when_epub_missing_on_disk(self, tmp_path: Path) -> None:
        library_root = tmp_path / "library"
        library_root.mkdir()

        data, content_type = get_or_extract_cover(
            book_id=1, epub_path=tmp_path / "missing.epub", library_root=library_root
        )
        assert data == PLACEHOLDER_SVG
        assert content_type == PLACEHOLDER_CONTENT_TYPE

    def test_caches_png_with_png_extension(self, tmp_path: Path) -> None:
        book = epub.EpubBook()
        book.set_identifier("png-cover")
        book.set_title("PNG Cover")
        book.set_language("en")
        book.add_author("Anon")
        png = b"\x89PNG\r\n\x1a\n" + b"pngdata" * 4
        book.set_cover("cover.png", png)
        chapter = epub.EpubHtml(title="c", file_name="c.xhtml", lang="en")
        chapter.content = b"<html><body><p>x</p></body></html>"
        book.add_item(chapter)
        book.toc = [epub.Link("c.xhtml", "c", "c")]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = ["nav", chapter]
        epub_path = tmp_path / "pngfix.epub"
        epub.write_epub(str(epub_path), book)

        library_root = tmp_path / "library"
        library_root.mkdir()

        data, content_type = get_or_extract_cover(
            book_id=99, epub_path=epub_path, library_root=library_root
        )
        assert content_type == "image/png"
        assert data.startswith(b"\x89PNG")
        # Cache extension matches the media type for browser-friendliness.
        assert (library_root / ".covers" / "99.png").exists()


class TestInvalidateCover:
    def test_removes_cached_entry(self, tmp_path: Path, epub_path: Path) -> None:
        library_root = tmp_path / "library"
        library_root.mkdir()
        get_or_extract_cover(book_id=5, epub_path=epub_path, library_root=library_root)
        cached = library_root / ".covers" / "5.jpg"
        assert cached.exists()

        invalidate_cover(library_root, 5)
        assert not cached.exists()

    def test_no_error_when_nothing_cached(self, tmp_path: Path) -> None:
        library_root = tmp_path / "library"
        library_root.mkdir()
        # Should be a quiet no-op even with no .covers directory.
        invalidate_cover(library_root, 123)

    def test_only_removes_target_book(self, tmp_path: Path, epub_path: Path) -> None:
        library_root = tmp_path / "library"
        library_root.mkdir()
        get_or_extract_cover(book_id=1, epub_path=epub_path, library_root=library_root)
        get_or_extract_cover(book_id=2, epub_path=epub_path, library_root=library_root)

        invalidate_cover(library_root, 1)
        assert not (library_root / ".covers" / "1.jpg").exists()
        assert (library_root / ".covers" / "2.jpg").exists()
