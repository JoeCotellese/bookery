# ABOUTME: Unit tests for genre auto-assignment during the import pipeline.
# ABOUTME: Validates that subjects trigger genre normalization and DB storage.

from pathlib import Path

import pytest
from ebooklib import epub

from bookery.core.importer import import_books
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library


@pytest.fixture()
def catalog(tmp_path: Path) -> LibraryCatalog:
    """Provide a LibraryCatalog backed by a temporary database."""
    conn = open_library(tmp_path / "import_genre_test.db")
    return LibraryCatalog(conn)


def _make_epub(path: Path, title: str, *, author: str | None = None) -> Path:
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


class TestImportWithGenres:
    """Tests for genre auto-assignment during import."""

    def test_import_with_subjects_assigns_genres(
        self, catalog: LibraryCatalog, tmp_path: Path
    ) -> None:
        """Import with subjects triggers genre normalization and assignment."""
        epub_path = _make_epub(tmp_path / "fiction.epub", "A Fiction Book")

        from bookery.core.importer import MatchResult
        from bookery.metadata.types import BookMetadata

        def match_fn(meta: BookMetadata, path: Path) -> MatchResult:
            meta.subjects = ["fiction", "mystery", "detective stories"]
            return MatchResult(metadata=meta)

        result = import_books([epub_path], catalog, match_fn=match_fn)
        assert result.added == 1

        # Check genres were assigned
        genres = catalog.get_genres_for_book(1)
        genre_names = [name for name, _ in genres]
        assert "Literary Fiction" in genre_names
        assert "Mystery & Thriller" in genre_names

        # Check primary was set
        primary = catalog.get_primary_genre(1)
        assert primary is not None

    def test_import_without_subjects_no_genre(
        self, catalog: LibraryCatalog, tmp_path: Path
    ) -> None:
        """Import without subjects assigns no genres."""
        epub_path = _make_epub(tmp_path / "plain.epub", "Plain Book")

        result = import_books([epub_path], catalog)
        assert result.added == 1

        genres = catalog.get_genres_for_book(1)
        assert genres == []

    def test_import_with_all_unmatched_subjects(
        self, catalog: LibraryCatalog, tmp_path: Path
    ) -> None:
        """Import with unmatched subjects stores subjects but no genre."""
        epub_path = _make_epub(tmp_path / "weird.epub", "Weird Book")

        from bookery.core.importer import MatchResult
        from bookery.metadata.types import BookMetadata

        def match_fn(meta: BookMetadata, path: Path) -> MatchResult:
            meta.subjects = ["xyzzy", "basket weaving"]
            return MatchResult(metadata=meta)

        result = import_books([epub_path], catalog, match_fn=match_fn)
        assert result.added == 1

        # Subjects stored
        record = catalog.get_by_id(1)
        assert record is not None
        assert record.metadata.subjects == ["xyzzy", "basket weaving"]

        # No genres assigned
        genres = catalog.get_genres_for_book(1)
        assert genres == []
