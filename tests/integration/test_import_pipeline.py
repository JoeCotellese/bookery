# ABOUTME: Integration tests for the import pipeline with real DB operations.
# ABOUTME: Validates end-to-end import flow including dedup across imports.

import shutil
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner
from ebooklib import epub

from bookery.cli import cli
from bookery.core.converter import ConvertResult
from bookery.core.importer import import_books
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


def _make_epub(path: Path, title: str, author: str | None = None) -> Path:
    """Create a minimal EPUB with the given title."""
    book = epub.EpubBook()
    book.set_identifier(f"id-{title}")
    book.set_title(title)
    book.set_language("en")
    if author:
        book.add_author(author)

    chapter = epub.EpubHtml(
        title="Chapter 1",
        file_name="chap01.xhtml",
        lang="en",
    )
    chapter.content = (
        b"<html><body><h1>Chapter 1</h1><p>Content for " + title.encode() + b".</p></body></html>"
    )
    book.add_item(chapter)
    book.toc = [epub.Link("chap01.xhtml", "Chapter 1", "chap01")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]

    epub.write_epub(str(path), book)
    return path


class TestImportPipelineIntegration:
    """Integration tests for full import pipeline."""

    def test_import_creates_db_and_catalogs(self, tmp_path: Path) -> None:
        """Import to a fresh DB creates records with correct metadata."""
        db_path = tmp_path / "lib.db"
        books_dir = tmp_path / "books"
        books_dir.mkdir()

        _make_epub(books_dir / "rose.epub", "The Name of the Rose", "Umberto Eco")
        _make_epub(books_dir / "pendulum.epub", "Foucault's Pendulum", "Umberto Eco")

        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        paths = sorted(books_dir.glob("*.epub"))
        result = import_books(paths, catalog, library_root=tmp_path / "lib")

        assert result.added == 2
        records = catalog.list_all()
        assert len(records) == 2
        titles = {r.metadata.title for r in records}
        assert "The Name of the Rose" in titles
        assert "Foucault's Pendulum" in titles
        conn.close()

    def test_reimport_detects_duplicates(self, tmp_path: Path) -> None:
        """Second import of the same files reports all skipped."""
        db_path = tmp_path / "lib.db"
        books_dir = tmp_path / "books"
        books_dir.mkdir()

        _make_epub(books_dir / "book1.epub", "Book One")
        _make_epub(books_dir / "book2.epub", "Book Two")

        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        paths = sorted(books_dir.glob("*.epub"))

        result1 = import_books(paths, catalog, library_root=tmp_path / "lib")
        assert result1.added == 2

        result2 = import_books(paths, catalog, library_root=tmp_path / "lib")
        assert result2.added == 0
        assert result2.skipped == 2
        conn.close()

    def test_copy_of_same_file_is_detected(self, tmp_path: Path) -> None:
        """A byte-identical copy in a different directory is detected as duplicate."""
        db_path = tmp_path / "lib.db"
        dir_a = tmp_path / "dir_a"
        dir_b = tmp_path / "dir_b"
        dir_a.mkdir()
        dir_b.mkdir()

        original = _make_epub(dir_a / "book.epub", "Test Book")
        shutil.copy2(original, dir_b / "book_copy.epub")

        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)

        result1 = import_books([dir_a / "book.epub"], catalog, library_root=tmp_path / "lib")
        assert result1.added == 1

        result2 = import_books([dir_b / "book_copy.epub"], catalog, library_root=tmp_path / "lib")
        assert result2.added == 0
        assert result2.skipped == 1
        conn.close()


class TestFindDuplicate:
    """Integration tests for catalog.find_duplicate() with real DB."""

    def test_isbn_match(self, tmp_path: Path) -> None:
        """Book with same ISBN (normalized) is detected as duplicate."""
        conn = open_library(tmp_path / "test.db")
        catalog = LibraryCatalog(conn)

        # Insert a book with ISBN
        existing = BookMetadata(
            title="The Name of the Rose",
            authors=["Umberto Eco"],
            isbn="9780151446476",
        )
        existing.source_path = tmp_path / "rose.epub"
        catalog.add_book(existing, file_hash="abc123")

        # Search with same ISBN, different format
        candidate = BookMetadata(
            title="Name of the Rose",
            authors=["Eco, Umberto"],
            isbn="978-0-15-144647-6",
        )
        result = catalog.find_duplicate(candidate)

        assert result is not None
        assert result.reason == "isbn"
        assert result.record.metadata.title == "The Name of the Rose"
        conn.close()

    def test_isbn10_matches_isbn13(self, tmp_path: Path) -> None:
        """ISBN-10 in candidate matches ISBN-13 in catalog."""
        conn = open_library(tmp_path / "test.db")
        catalog = LibraryCatalog(conn)

        existing = BookMetadata(
            title="The Name of the Rose",
            authors=["Umberto Eco"],
            isbn="9780151446476",
        )
        existing.source_path = tmp_path / "rose.epub"
        catalog.add_book(existing, file_hash="abc123")

        candidate = BookMetadata(
            title="Whatever",
            authors=["Whatever"],
            isbn="0151446474",
        )
        result = catalog.find_duplicate(candidate)

        assert result is not None
        assert result.reason == "isbn"
        conn.close()

    def test_title_author_match(self, tmp_path: Path) -> None:
        """Book with same title+author (normalized) is detected as duplicate."""
        conn = open_library(tmp_path / "test.db")
        catalog = LibraryCatalog(conn)

        existing = BookMetadata(
            title="The Name of the Rose",
            authors=["Umberto Eco"],
        )
        existing.source_path = tmp_path / "rose.epub"
        catalog.add_book(existing, file_hash="abc123")

        # Different article, different author format
        candidate = BookMetadata(
            title="  The  Name of the  Rose  ",
            authors=["Eco, Umberto"],
        )
        result = catalog.find_duplicate(candidate)

        assert result is not None
        assert result.reason == "title_author"
        conn.close()

    def test_isbn_takes_priority_over_title_author(self, tmp_path: Path) -> None:
        """When both ISBN and title+author match, reason is 'isbn'."""
        conn = open_library(tmp_path / "test.db")
        catalog = LibraryCatalog(conn)

        existing = BookMetadata(
            title="The Name of the Rose",
            authors=["Umberto Eco"],
            isbn="9780151446476",
        )
        existing.source_path = tmp_path / "rose.epub"
        catalog.add_book(existing, file_hash="abc123")

        candidate = BookMetadata(
            title="The Name of the Rose",
            authors=["Umberto Eco"],
            isbn="978-0-15-144647-6",
        )
        result = catalog.find_duplicate(candidate)

        assert result is not None
        assert result.reason == "isbn"
        conn.close()

    def test_no_match_returns_none(self, tmp_path: Path) -> None:
        """No duplicate → returns None."""
        conn = open_library(tmp_path / "test.db")
        catalog = LibraryCatalog(conn)

        existing = BookMetadata(
            title="The Name of the Rose",
            authors=["Umberto Eco"],
        )
        existing.source_path = tmp_path / "rose.epub"
        catalog.add_book(existing, file_hash="abc123")

        candidate = BookMetadata(
            title="Dune",
            authors=["Frank Herbert"],
        )
        result = catalog.find_duplicate(candidate)

        assert result is None
        conn.close()

    def test_empty_catalog_returns_none(self, tmp_path: Path) -> None:
        """Empty catalog → returns None."""
        conn = open_library(tmp_path / "test.db")
        catalog = LibraryCatalog(conn)

        candidate = BookMetadata(
            title="Dune",
            authors=["Frank Herbert"],
        )
        result = catalog.find_duplicate(candidate)

        assert result is None
        conn.close()


class TestImportMetadataDedup:
    """Integration tests for metadata-level dedup in the import pipeline."""

    def test_different_file_same_isbn_skipped(self, tmp_path: Path) -> None:
        """Two different files with same ISBN → second is skipped as metadata dup."""
        conn = open_library(tmp_path / "test.db")
        catalog = LibraryCatalog(conn)

        epub1 = _make_epub_with_isbn(
            tmp_path / "rose_v1.epub",
            "The Name of the Rose",
            "Umberto Eco",
            "9780151446476",
            content_marker="edition-1",
        )
        epub2 = _make_epub_with_isbn(
            tmp_path / "rose_v2.epub",
            "Name of the Rose",
            "Eco, Umberto",
            "978-0-15-144647-6",
            content_marker="edition-2",
        )

        result1 = import_books([epub1], catalog, library_root=tmp_path / "lib")
        assert result1.added == 1

        result2 = import_books([epub2], catalog, library_root=tmp_path / "lib")
        assert result2.added == 0
        assert result2.skipped == 1
        assert result2.skipped_metadata == 1
        assert len(result2.skip_details) == 1
        assert result2.skip_details[0].reason == "isbn"
        conn.close()

    def test_different_file_same_title_author_skipped(self, tmp_path: Path) -> None:
        """Two different files with same title+author → second is skipped."""
        conn = open_library(tmp_path / "test.db")
        catalog = LibraryCatalog(conn)

        epub1 = _make_epub_unique(
            tmp_path / "rose_v1.epub",
            "The Name of the Rose",
            "Umberto Eco",
            content_marker="version-1",
        )
        epub2 = _make_epub_unique(
            tmp_path / "rose_v2.epub",
            "The Name of the Rose",
            "Umberto Eco",
            content_marker="version-2",
        )

        result1 = import_books([epub1], catalog, library_root=tmp_path / "lib")
        assert result1.added == 1

        result2 = import_books([epub2], catalog, library_root=tmp_path / "lib")
        assert result2.added == 0
        assert result2.skipped == 1
        assert result2.skipped_metadata == 1
        assert len(result2.skip_details) == 1
        assert result2.skip_details[0].reason == "title_author"
        conn.close()

    def test_force_duplicates_imports_anyway(self, tmp_path: Path) -> None:
        """With force_duplicates=True, metadata dups are imported with warning."""
        conn = open_library(tmp_path / "test.db")
        catalog = LibraryCatalog(conn)

        epub1 = _make_epub_unique(
            tmp_path / "rose_v1.epub",
            "The Name of the Rose",
            "Umberto Eco",
            content_marker="version-1",
        )
        epub2 = _make_epub_unique(
            tmp_path / "rose_v2.epub",
            "The Name of the Rose",
            "Umberto Eco",
            content_marker="version-2",
        )

        import_books([epub1], catalog, library_root=tmp_path / "lib")
        result = import_books(
            [epub2], catalog, library_root=tmp_path / "lib", force_duplicates=True
        )

        assert result.added == 1
        assert result.forced == 1
        assert result.skipped == 0
        assert len(result.skip_details) == 1
        assert result.skip_details[0].reason == "title_author"
        conn.close()


def _make_epub_unique(
    path: Path,
    title: str,
    author: str,
    *,
    content_marker: str = "",
) -> Path:
    """Create a minimal EPUB with unique content to produce distinct hashes."""
    book = epub.EpubBook()
    book.set_identifier(f"id-{title}-{content_marker}")
    book.set_title(title)
    book.set_language("en")
    book.add_author(author)

    chapter = epub.EpubHtml(
        title="Chapter 1",
        file_name="chap01.xhtml",
        lang="en",
    )
    chapter.content = (
        b"<html><body><h1>Chapter 1</h1>"
        b"<p>Content: " + content_marker.encode() + b".</p>"
        b"</body></html>"
    )
    book.add_item(chapter)
    book.toc = [epub.Link("chap01.xhtml", "Chapter 1", "chap01")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]

    epub.write_epub(str(path), book)
    return path


def _make_epub_with_isbn(
    path: Path,
    title: str,
    author: str,
    isbn: str,
    *,
    content_marker: str = "",
) -> Path:
    """Create a minimal EPUB with title, author, ISBN, and unique content.

    Sets the ISBN as the primary identifier so ebooklib's _detect_isbn
    can find it (ebooklib does not preserve additional DC identifiers).
    """
    book = epub.EpubBook()
    # Set ISBN as primary identifier so it gets extracted
    book.set_identifier(isbn)
    book.set_title(title)
    book.set_language("en")
    book.add_author(author)

    chapter = epub.EpubHtml(
        title="Chapter 1",
        file_name="chap01.xhtml",
        lang="en",
    )
    chapter.content = (
        b"<html><body><h1>Chapter 1</h1>"
        b"<p>Content: " + content_marker.encode() + b".</p>"
        b"</body></html>"
    )
    book.add_item(chapter)
    book.toc = [epub.Link("chap01.xhtml", "Chapter 1", "chap01")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]

    epub.write_epub(str(path), book)
    return path


class TestImportConvertIntegration:
    """Integration tests for convert+import pipeline."""

    def test_import_convert_mixed_directory(self, tmp_path: Path) -> None:
        """Dir with EPUBs + MOBIs and --convert → all cataloged."""
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()

        # Create a real EPUB
        _make_epub(scan_dir / "real.epub", "Real Book", "Author A")

        # Create a fake MOBI in a subdirectory so filter_redundant_mobis
        # doesn't skip it (an EPUB in the same dir would cause dedup)
        mobi_dir = scan_dir / "mobi"
        mobi_dir.mkdir()
        mobi_path = mobi_dir / "converted.mobi"
        mobi_path.write_bytes(b"fake mobi")

        # Create another real EPUB that convert_one will "produce"
        converted_epub = _make_epub(
            tmp_path / "converted.epub",
            "Converted Book",
            "Author B",
        )
        fake_result = ConvertResult(
            source=mobi_path,
            epub_path=converted_epub,
            success=True,
        )

        db_path = tmp_path / "test.db"
        runner = CliRunner()
        with patch(
            "bookery.core.converter.convert_one",
            return_value=fake_result,
        ):
            result = runner.invoke(
                cli,
                ["import", str(scan_dir), "--convert", "--db", str(db_path)],
            )

        assert result.exit_code == 0, result.output
        assert "Converted 1 of 1" in result.output

        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        records = catalog.list_all()
        titles = {r.metadata.title for r in records}
        assert len(records) == 2
        assert "Real Book" in titles
        assert "Converted Book" in titles
        conn.close()
