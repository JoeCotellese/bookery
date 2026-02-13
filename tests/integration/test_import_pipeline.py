# ABOUTME: Integration tests for the import pipeline with real DB operations.
# ABOUTME: Validates end-to-end import flow including dedup across imports.

import shutil
from pathlib import Path

from ebooklib import epub

from bookery.core.importer import import_books
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
        result = import_books(paths, catalog)

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

        result1 = import_books(paths, catalog)
        assert result1.added == 2

        result2 = import_books(paths, catalog)
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

        result1 = import_books([dir_a / "book.epub"], catalog)
        assert result1.added == 1

        result2 = import_books([dir_b / "book_copy.epub"], catalog)
        assert result2.added == 0
        assert result2.skipped == 1
        conn.close()
