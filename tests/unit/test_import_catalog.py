# ABOUTME: Unit tests for the import pipeline (catalog-as-is mode).
# ABOUTME: Validates file cataloging, dedup, error handling, and result tracking.

from pathlib import Path

import pytest
from ebooklib import epub

from bookery.core.importer import import_books
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library


@pytest.fixture()
def catalog(tmp_path: Path) -> LibraryCatalog:
    """Provide a LibraryCatalog backed by a temporary database."""
    conn = open_library(tmp_path / "import_test.db")
    return LibraryCatalog(conn)


def _make_epub(path: Path, title: str, author: str | None = None) -> Path:
    """Create a minimal EPUB with the given title."""
    book = epub.EpubBook()
    book.set_identifier(f"id-{title}")
    book.set_title(title)
    book.set_language("en")
    if author:
        book.add_author(author)

    chapter = epub.EpubHtml(
        title="Chapter 1", file_name="chap01.xhtml", lang="en",
    )
    chapter.content = (
        b"<html><body><h1>Chapter 1</h1>"
        b"<p>Content for " + title.encode() + b".</p>"
        b"</body></html>"
    )
    book.add_item(chapter)
    book.toc = [epub.Link("chap01.xhtml", "Chapter 1", "chap01")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]

    epub.write_epub(str(path), book)
    return path


class TestImportBooks:
    """Tests for import_books function."""

    def test_import_single_file(
        self, tmp_path: Path, catalog: LibraryCatalog,
    ) -> None:
        """Importing a single EPUB adds one record to the catalog."""
        epub_path = _make_epub(tmp_path / "book.epub", "Test Book", "Author")
        result = import_books([epub_path], catalog)

        assert result.added == 1
        assert result.skipped == 0
        assert result.errors == 0

        records = catalog.list_all()
        assert len(records) == 1
        assert records[0].metadata.title == "Test Book"

    def test_import_directory_of_files(
        self, tmp_path: Path, catalog: LibraryCatalog,
    ) -> None:
        """Importing multiple EPUBs adds all to the catalog."""
        for i in range(3):
            _make_epub(tmp_path / f"book_{i}.epub", f"Book {i}")

        paths = sorted(tmp_path.glob("*.epub"))
        result = import_books(paths, catalog)

        assert result.added == 3
        records = catalog.list_all()
        assert len(records) == 3

    def test_import_skips_duplicates(
        self, tmp_path: Path, catalog: LibraryCatalog,
    ) -> None:
        """Importing the same file twice adds it once and skips the second."""
        epub_path = _make_epub(tmp_path / "book.epub", "Test Book")

        result1 = import_books([epub_path], catalog)
        result2 = import_books([epub_path], catalog)

        assert result1.added == 1
        assert result2.added == 0
        assert result2.skipped == 1

        records = catalog.list_all()
        assert len(records) == 1

    def test_import_records_source_path(
        self, tmp_path: Path, catalog: LibraryCatalog,
    ) -> None:
        """source_path in the DB matches the original file location."""
        epub_path = _make_epub(tmp_path / "book.epub", "Test Book")
        import_books([epub_path], catalog)

        records = catalog.list_all()
        assert len(records) == 1
        assert records[0].source_path == epub_path

    def test_import_stores_file_hash(
        self, tmp_path: Path, catalog: LibraryCatalog,
    ) -> None:
        """File hash is computed and stored in the catalog."""
        epub_path = _make_epub(tmp_path / "book.epub", "Test Book")
        import_books([epub_path], catalog)

        records = catalog.list_all()
        assert len(records) == 1
        assert len(records[0].file_hash) == 64  # SHA-256 hex

    def test_import_no_output_path_for_catalog_only(
        self, tmp_path: Path, catalog: LibraryCatalog,
    ) -> None:
        """Catalog-only import sets output_path to None."""
        epub_path = _make_epub(tmp_path / "book.epub", "Test Book")
        import_books([epub_path], catalog)

        records = catalog.list_all()
        assert len(records) == 1
        assert records[0].output_path is None

    def test_import_handles_corrupt_files(
        self, tmp_path: Path, catalog: LibraryCatalog,
    ) -> None:
        """Corrupt files are logged as errors; valid files still imported."""
        good = _make_epub(tmp_path / "good.epub", "Good Book")
        bad = tmp_path / "bad.epub"
        bad.write_text("not a valid epub")

        result = import_books([good, bad], catalog)

        assert result.added == 1
        assert result.errors == 1
        assert len(result.error_details) == 1
        assert result.error_details[0][0] == bad

    def test_import_returns_result_summary(
        self, tmp_path: Path, catalog: LibraryCatalog,
    ) -> None:
        """ImportResult has correct totals for mixed outcomes."""
        epub1 = _make_epub(tmp_path / "a.epub", "Book A")
        epub2 = _make_epub(tmp_path / "b.epub", "Book B")
        corrupt = tmp_path / "c.epub"
        corrupt.write_text("corrupt")

        # First import: 2 added, 1 error
        result1 = import_books([epub1, epub2, corrupt], catalog)
        assert result1.added == 2
        assert result1.errors == 1
        assert result1.skipped == 0

        # Second import: 0 added, 2 skipped, 1 error
        result2 = import_books([epub1, epub2, corrupt], catalog)
        assert result2.added == 0
        assert result2.skipped == 2
        assert result2.errors == 1
