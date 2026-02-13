# ABOUTME: Unit tests for the directory scanner module.
# ABOUTME: Tests BookEntry, ScanResult dataclasses, Calibre path parsing, and scan logic.

from pathlib import Path

import pytest

from bookery.core.scanner import EBOOK_EXTENSIONS, BookEntry


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
