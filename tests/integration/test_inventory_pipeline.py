# ABOUTME: Integration tests for inventory scan + DB cross-reference.
# ABOUTME: Validates that scanned books are correctly matched against the catalog.

from pathlib import Path

from ebooklib import epub

from bookery.core.scanner import cross_reference_db, scan_directory
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library


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
        b"<p>Content.</p>"
        b"</body></html>"
    )
    book.add_item(chapter)
    book.toc = [epub.Link("chap01.xhtml", "Chapter 1", "chap01")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]

    epub.write_epub(str(path), book)
    return path


class TestDbCrossReference:
    """cross_reference_db matches scan results against the catalog."""

    def _setup_catalog(self, tmp_path: Path, epub_paths: list[Path]) -> LibraryCatalog:
        """Create a DB and import EPUBs into the catalog."""
        from bookery.core.importer import import_books

        db_path = tmp_path / "test.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        import_books(epub_paths, catalog)
        return catalog

    def test_cataloged_book_found(self, tmp_path: Path):
        """A scanned book whose source_path is in the catalog → in_catalog."""
        books_dir = tmp_path / "Author" / "My Book (1)"
        books_dir.mkdir(parents=True)
        epub_path = _make_epub(books_dir / "My Book.epub", "My Book", "Author")

        catalog = self._setup_catalog(tmp_path, [epub_path])
        scan_result = scan_directory(tmp_path / "Author")

        xref = cross_reference_db(scan_result, catalog)
        assert len(xref.in_catalog) == 1
        assert len(xref.not_in_catalog) == 0

    def test_uncataloged_book_identified(self, tmp_path: Path):
        """A scanned book not in the catalog → not_in_catalog."""
        # Cataloged book
        cataloged_dir = tmp_path / "Author" / "Cataloged (1)"
        cataloged_dir.mkdir(parents=True)
        epub_path = _make_epub(
            cataloged_dir / "Cataloged.epub", "Cataloged", "Author"
        )

        catalog = self._setup_catalog(tmp_path, [epub_path])

        # Uncataloged book (MOBI only, never imported)
        uncataloged_dir = tmp_path / "Author" / "Uncataloged (2)"
        uncataloged_dir.mkdir(parents=True)
        (uncataloged_dir / "Uncataloged.mobi").write_bytes(b"fake")

        scan_root = tmp_path / "Author"
        scan_result = scan_directory(scan_root)

        xref = cross_reference_db(scan_result, catalog)
        assert len(xref.in_catalog) == 1
        assert len(xref.not_in_catalog) == 1
        assert xref.not_in_catalog[0].title == "Uncataloged"

    def test_empty_catalog(self, tmp_path: Path):
        """Empty catalog → all scanned books are not_in_catalog."""
        db_path = tmp_path / "empty.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)

        book_dir = tmp_path / "Author" / "Book (1)"
        book_dir.mkdir(parents=True)
        (book_dir / "Book.epub").write_bytes(b"fake")

        scan_result = scan_directory(tmp_path / "Author")
        xref = cross_reference_db(scan_result, catalog)

        assert len(xref.in_catalog) == 0
        assert len(xref.not_in_catalog) == 1
        conn.close()

    def test_empty_scan(self, tmp_path: Path):
        """Empty scan → both lists empty regardless of catalog content."""
        db_path = tmp_path / "test.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)

        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        scan_result = scan_directory(empty_dir)
        xref = cross_reference_db(scan_result, catalog)

        assert len(xref.in_catalog) == 0
        assert len(xref.not_in_catalog) == 0
        conn.close()
