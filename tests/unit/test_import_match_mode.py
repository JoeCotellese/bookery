# ABOUTME: Unit tests for import --match mode integration.
# ABOUTME: Validates that match_fn callback is invoked and results are cataloged.

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from ebooklib import epub

from bookery.core.importer import MatchResult, import_books
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


@pytest.fixture()
def catalog(tmp_path: Path) -> LibraryCatalog:
    """Provide a LibraryCatalog backed by a temporary database."""
    conn = open_library(tmp_path / "match_test.db")
    return LibraryCatalog(conn)


def _make_epub(path: Path, title: str, author: str | None = None) -> Path:
    """Create a minimal EPUB."""
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


class TestImportMatchMode:
    """Tests for import_books with match_fn callback."""

    def test_match_fn_is_called(
        self, tmp_path: Path, catalog: LibraryCatalog,
    ) -> None:
        """match_fn is invoked for each non-duplicate file."""
        epub_path = _make_epub(tmp_path / "book.epub", "Test Book")

        match_fn = MagicMock(return_value=MatchResult(
            metadata=BookMetadata(title="Matched Title", authors=["Author"]),
            output_path=Path("/output/matched.epub"),
        ))

        import_books([epub_path], catalog, match_fn=match_fn)
        match_fn.assert_called_once()

    def test_match_fn_result_is_cataloged(
        self, tmp_path: Path, catalog: LibraryCatalog,
    ) -> None:
        """Matched metadata and output_path are stored in the catalog."""
        epub_path = _make_epub(tmp_path / "book.epub", "Test Book")

        match_fn = MagicMock(return_value=MatchResult(
            metadata=BookMetadata(
                title="Better Title",
                authors=["Correct Author"],
                isbn="9780000000000",
            ),
            output_path=Path("/output/better.epub"),
        ))

        import_books([epub_path], catalog, match_fn=match_fn)

        records = catalog.list_all()
        assert len(records) == 1
        assert records[0].metadata.title == "Better Title"
        assert records[0].metadata.authors == ["Correct Author"]
        assert records[0].output_path == Path("/output/better.epub")

    def test_match_fn_none_catalogs_original(
        self, tmp_path: Path, catalog: LibraryCatalog,
    ) -> None:
        """When match_fn returns None (user skipped), original metadata is cataloged."""
        epub_path = _make_epub(tmp_path / "book.epub", "Original Title")

        match_fn = MagicMock(return_value=None)

        import_books([epub_path], catalog, match_fn=match_fn)

        records = catalog.list_all()
        assert len(records) == 1
        assert records[0].metadata.title == "Original Title"
        assert records[0].output_path is None

    def test_match_fn_not_called_for_duplicates(
        self, tmp_path: Path, catalog: LibraryCatalog,
    ) -> None:
        """Duplicate files are skipped before match_fn is invoked."""
        epub_path = _make_epub(tmp_path / "book.epub", "Test Book")

        match_fn = MagicMock(return_value=MatchResult(
            metadata=BookMetadata(title="Matched"),
            output_path=None,
        ))

        import_books([epub_path], catalog, match_fn=match_fn)
        import_books([epub_path], catalog, match_fn=match_fn)

        # Only called once — second import is skipped
        assert match_fn.call_count == 1

    def test_dedup_still_works_in_match_mode(
        self, tmp_path: Path, catalog: LibraryCatalog,
    ) -> None:
        """Duplicate detection works the same in match mode."""
        epub_path = _make_epub(tmp_path / "book.epub", "Test Book")

        match_fn = MagicMock(return_value=MatchResult(
            metadata=BookMetadata(title="Matched"),
            output_path=None,
        ))

        result1 = import_books([epub_path], catalog, match_fn=match_fn)
        result2 = import_books([epub_path], catalog, match_fn=match_fn)

        assert result1.added == 1
        assert result2.skipped == 1
