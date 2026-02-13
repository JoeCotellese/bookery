# ABOUTME: Unit tests for the directory scanner module.
# ABOUTME: Tests BookEntry, ScanResult dataclasses, Calibre path parsing, and scan logic.

from pathlib import Path

import pytest

from bookery.core.scanner import (
    EBOOK_EXTENSIONS,
    BookEntry,
    ScanResult,
    _parse_calibre_dir,
    scan_directory,
)


class TestEbookExtensions:
    """EBOOK_EXTENSIONS should contain all supported ebook formats."""

    def test_contains_all_expected_formats(self):
        expected = {".epub", ".mobi", ".azw3", ".azw", ".pdf", ".txt", ".cbz", ".cbr"}
        assert EBOOK_EXTENSIONS == expected

    def test_is_frozenset(self):
        assert isinstance(EBOOK_EXTENSIONS, frozenset)


class TestBookEntry:
    """BookEntry should represent a single book directory with its formats."""

    def test_name_with_author_and_title(self):
        entry = BookEntry(
            directory=Path("/books/Author/Title (123)"),
            author="Umberto Eco",
            title="The Name of the Rose",
            formats={".epub", ".mobi"},
        )
        assert entry.name == "The Name of the Rose - Umberto Eco"

    def test_name_without_author(self):
        entry = BookEntry(
            directory=Path("/books/Unknown/Some Book (1)"),
            author=None,
            title="Some Book",
            formats={".epub"},
        )
        assert entry.name == "Some Book"

    def test_name_without_title(self):
        entry = BookEntry(
            directory=Path("/books/Author/unknown"),
            author="Author",
            title=None,
            formats={".mobi"},
        )
        assert entry.name == "unknown"

    def test_name_without_author_or_title(self):
        entry = BookEntry(
            directory=Path("/books/my-book"),
            author=None,
            title=None,
            formats={".pdf"},
        )
        assert entry.name == "my-book"

    def test_has_format_with_dot(self):
        entry = BookEntry(
            directory=Path("/books/a"),
            author=None,
            title=None,
            formats={".epub", ".mobi"},
        )
        assert entry.has_format(".epub") is True
        assert entry.has_format(".pdf") is False

    def test_has_format_without_dot(self):
        entry = BookEntry(
            directory=Path("/books/a"),
            author=None,
            title=None,
            formats={".epub", ".mobi"},
        )
        assert entry.has_format("epub") is True
        assert entry.has_format("pdf") is False

    def test_has_format_case_insensitive(self):
        entry = BookEntry(
            directory=Path("/books/a"),
            author=None,
            title=None,
            formats={".epub"},
        )
        assert entry.has_format("EPUB") is True
        assert entry.has_format(".EPUB") is True
        assert entry.has_format("Epub") is True


class TestScanResult:
    """ScanResult should aggregate BookEntry results with computed properties."""

    def _make_entry(self, formats: set[str], title: str = "Book") -> BookEntry:
        return BookEntry(
            directory=Path(f"/books/{title}"),
            author="Author",
            title=title,
            formats=formats,
        )

    def test_total_books(self):
        result = ScanResult(
            books=[self._make_entry({".epub"}), self._make_entry({".mobi"})],
            format_counts={".epub": 1, ".mobi": 1},
            scan_root=Path("/books"),
        )
        assert result.total_books == 2

    def test_total_books_empty(self):
        result = ScanResult(
            books=[],
            format_counts={},
            scan_root=Path("/books"),
        )
        assert result.total_books == 0

    def test_missing_format_filters_correctly(self):
        epub_book = self._make_entry({".epub"}, title="Has EPUB")
        mobi_book = self._make_entry({".mobi"}, title="Only MOBI")
        both_book = self._make_entry({".epub", ".mobi"}, title="Has Both")

        result = ScanResult(
            books=[epub_book, mobi_book, both_book],
            format_counts={".epub": 2, ".mobi": 2},
            scan_root=Path("/books"),
        )

        missing = result.missing_format(".epub")
        assert len(missing) == 1
        assert missing[0].title == "Only MOBI"

    def test_missing_format_none_missing(self):
        result = ScanResult(
            books=[self._make_entry({".epub"})],
            format_counts={".epub": 1},
            scan_root=Path("/books"),
        )
        assert result.missing_format(".epub") == []

    def test_missing_format_all_missing(self):
        result = ScanResult(
            books=[
                self._make_entry({".mobi"}, title="A"),
                self._make_entry({".pdf"}, title="B"),
            ],
            format_counts={".mobi": 1, ".pdf": 1},
            scan_root=Path("/books"),
        )
        missing = result.missing_format(".epub")
        assert len(missing) == 2


class TestParseCalibreDir:
    """_parse_calibre_dir extracts author and title from Calibre directory paths."""

    def test_standard_calibre_layout(self, tmp_path):
        """Author/Book Title (2739)/ → author='Author', title='Book Title'"""
        author_dir = tmp_path / "Umberto Eco"
        book_dir = author_dir / "The Name of the Rose (2739)"
        book_dir.mkdir(parents=True)

        author, title = _parse_calibre_dir(book_dir, scan_root=tmp_path)
        assert author == "Umberto Eco"
        assert title == "The Name of the Rose"

    def test_strips_trailing_calibre_id(self, tmp_path):
        """Trailing (digits) from Calibre should be stripped."""
        author_dir = tmp_path / "Author"
        book_dir = author_dir / "My Book (42)"
        book_dir.mkdir(parents=True)

        _, title = _parse_calibre_dir(book_dir, scan_root=tmp_path)
        assert title == "My Book"

    def test_preserves_parens_in_title(self, tmp_path):
        """Parenthetical text that isn't a bare Calibre ID should be preserved."""
        author_dir = tmp_path / "Author"
        book_dir = author_dir / "A Book (Vol 2) (99)"
        book_dir.mkdir(parents=True)

        _, title = _parse_calibre_dir(book_dir, scan_root=tmp_path)
        assert title == "A Book (Vol 2)"

    def test_no_calibre_id(self, tmp_path):
        """Directory without trailing (digits) returns dirname as title."""
        author_dir = tmp_path / "Author"
        book_dir = author_dir / "Just A Book"
        book_dir.mkdir(parents=True)

        author, title = _parse_calibre_dir(book_dir, scan_root=tmp_path)
        assert author == "Author"
        assert title == "Just A Book"

    def test_single_depth_returns_none_author(self, tmp_path):
        """Book dir directly under scan root → author is None."""
        book_dir = tmp_path / "Some Book (1)"
        book_dir.mkdir()

        author, title = _parse_calibre_dir(book_dir, scan_root=tmp_path)
        assert author is None
        assert title == "Some Book"


class TestScanDirectory:
    """scan_directory walks a tree and groups ebook files by leaf directory."""

    def test_empty_directory(self, tmp_path):
        result = scan_directory(tmp_path)
        assert result.total_books == 0
        assert result.format_counts == {}

    def test_single_book_single_format(self, tmp_path):
        book_dir = tmp_path / "Author" / "My Book (1)"
        book_dir.mkdir(parents=True)
        (book_dir / "My Book.epub").write_bytes(b"fake")

        result = scan_directory(tmp_path)
        assert result.total_books == 1
        assert result.books[0].formats == {".epub"}

    def test_multi_format_book(self, tmp_path):
        book_dir = tmp_path / "Author" / "My Book (1)"
        book_dir.mkdir(parents=True)
        (book_dir / "My Book.epub").write_bytes(b"fake")
        (book_dir / "My Book.mobi").write_bytes(b"fake")

        result = scan_directory(tmp_path)
        assert result.total_books == 1
        assert result.books[0].formats == {".epub", ".mobi"}

    def test_multiple_books(self, calibre_tree):
        result = scan_directory(calibre_tree)
        assert result.total_books == 3

    def test_ignores_non_ebook_files(self, tmp_path):
        book_dir = tmp_path / "Author" / "Book (1)"
        book_dir.mkdir(parents=True)
        (book_dir / "cover.jpg").write_bytes(b"image")
        (book_dir / "metadata.opf").write_text("<opf/>")

        result = scan_directory(tmp_path)
        # Directory with no ebook files should not be counted as a book
        assert result.total_books == 0

    def test_format_counts(self, calibre_tree):
        result = scan_directory(calibre_tree)
        assert result.format_counts[".epub"] == 1
        assert result.format_counts[".mobi"] == 2
        assert result.format_counts[".pdf"] == 1

    def test_calibre_layout_extracts_author_title(self, calibre_tree):
        result = scan_directory(calibre_tree)
        by_title = {b.title: b for b in result.books}

        assert "The Name of the Rose" in by_title
        rose = by_title["The Name of the Rose"]
        assert rose.author == "Umberto Eco"
        assert rose.formats == {".epub", ".mobi"}

        assert "Dune" in by_title
        dune = by_title["Dune"]
        assert dune.author == "Frank Herbert"

    def test_scan_root_is_set(self, calibre_tree):
        result = scan_directory(calibre_tree)
        assert result.scan_root == calibre_tree

    def test_directory_without_ebooks_ignored(self, tmp_path):
        """Directories containing only non-ebook files should be excluded."""
        (tmp_path / "just-images").mkdir()
        (tmp_path / "just-images" / "photo.jpg").write_bytes(b"img")

        book_dir = tmp_path / "Author" / "Real Book (1)"
        book_dir.mkdir(parents=True)
        (book_dir / "book.epub").write_bytes(b"fake")

        result = scan_directory(tmp_path)
        assert result.total_books == 1
