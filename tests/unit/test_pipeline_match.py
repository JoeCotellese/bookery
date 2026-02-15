# ABOUTME: Unit tests for the match_one() pipeline function.
# ABOUTME: Tests the shared match pipeline: read -> normalize -> search -> review -> write.

from pathlib import Path
from unittest.mock import MagicMock, patch

from ebooklib import epub

from bookery.core.pipeline import match_one
from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.types import BookMetadata


def _make_epub(tmp_path: Path, title: str = "Test Book", author: str = "Test Author") -> Path:
    """Create a minimal valid EPUB for testing."""
    book = epub.EpubBook()
    book.set_identifier("test-id")
    book.set_title(title)
    book.set_language("en")
    book.add_author(author)

    chapter = epub.EpubHtml(title="Ch1", file_name="ch01.xhtml", lang="en")
    chapter.content = b"<html><body><p>Content.</p></body></html>"
    book.add_item(chapter)
    book.toc = [epub.Link("ch01.xhtml", "Ch1", "ch01")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]

    filepath = tmp_path / "test_book.epub"
    epub.write_epub(str(filepath), book)
    return filepath


def _make_candidate(
    title: str, author: str, confidence: float, isbn: str | None = None,
) -> MetadataCandidate:
    return MetadataCandidate(
        metadata=BookMetadata(title=title, authors=[author], isbn=isbn, language="en"),
        confidence=confidence,
        source="openlibrary",
        source_id=f"test-{title}",
    )


class TestMatchOne:
    """Unit tests for match_one()."""

    def test_match_one_returns_matched_on_success(self, tmp_path: Path) -> None:
        """match_one returns status='matched' when provider finds a high-confidence candidate."""
        epub_path = _make_epub(tmp_path)
        output_dir = tmp_path / "output"
        candidate = _make_candidate("Better Title", "Better Author", 0.95)

        provider = MagicMock()
        provider.search_by_isbn.return_value = []
        provider.search_by_title_author.return_value = [candidate]

        review = MagicMock()
        review.review.return_value = candidate.metadata

        result = match_one(epub_path, provider, review, output_dir)

        assert result.status == "matched"
        assert result.metadata is not None
        assert result.metadata.title == "Better Title"
        assert result.output_path is not None
        assert result.output_path.exists()
        assert result.error is None

    def test_match_one_returns_skipped_when_no_candidates(self, tmp_path: Path) -> None:
        """match_one returns status='skipped' when provider finds no candidates."""
        epub_path = _make_epub(tmp_path)
        output_dir = tmp_path / "output"

        provider = MagicMock()
        provider.search_by_isbn.return_value = []
        provider.search_by_title_author.return_value = []

        review = MagicMock()

        result = match_one(epub_path, provider, review, output_dir)

        assert result.status == "skipped"
        assert result.metadata is None
        assert result.output_path is None
        review.review.assert_not_called()

    def test_match_one_returns_skipped_when_review_skips(self, tmp_path: Path) -> None:
        """match_one returns status='skipped' when review returns None (user skipped)."""
        epub_path = _make_epub(tmp_path)
        output_dir = tmp_path / "output"
        candidate = _make_candidate("Some Title", "Author", 0.9)

        provider = MagicMock()
        provider.search_by_isbn.return_value = []
        provider.search_by_title_author.return_value = [candidate]

        review = MagicMock()
        review.review.return_value = None

        result = match_one(epub_path, provider, review, output_dir)

        assert result.status == "skipped"
        assert result.metadata is None

    def test_match_one_returns_error_on_read_failure(self, tmp_path: Path) -> None:
        """match_one returns status='error' when EPUB can't be read."""
        epub_path = tmp_path / "bad.epub"
        epub_path.write_text("not a valid epub")
        output_dir = tmp_path / "output"

        provider = MagicMock()
        review = MagicMock()

        result = match_one(epub_path, provider, review, output_dir)

        assert result.status == "error"
        assert result.error is not None
        assert result.metadata is None
        provider.search_by_isbn.assert_not_called()

    def test_match_one_tries_isbn_first(self, tmp_path: Path) -> None:
        """match_one tries ISBN lookup before title/author search."""
        # Create EPUB with an ISBN as the primary identifier
        book = epub.EpubBook()
        book.set_identifier("978-0-123456-47-2")
        book.set_title("Test Book")
        book.set_language("en")
        book.add_author("Test Author")
        chapter = epub.EpubHtml(title="Ch1", file_name="ch01.xhtml", lang="en")
        chapter.content = b"<html><body><p>Content.</p></body></html>"
        book.add_item(chapter)
        book.toc = [epub.Link("ch01.xhtml", "Ch1", "ch01")]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = ["nav", chapter]
        epub_path = tmp_path / "isbn_book.epub"
        epub.write_epub(str(epub_path), book)

        output_dir = tmp_path / "output"
        candidate = _make_candidate("ISBN Match", "Author", 1.0, isbn="9780123456789")

        provider = MagicMock()
        provider.search_by_isbn.return_value = [candidate]

        review = MagicMock()
        review.review.return_value = candidate.metadata

        result = match_one(epub_path, provider, review, output_dir)

        assert result.status == "matched"
        # Should NOT fall through to title/author search when ISBN succeeds
        provider.search_by_title_author.assert_not_called()

    def test_match_one_falls_back_to_title_author(self, tmp_path: Path) -> None:
        """match_one falls back to title/author when ISBN returns no results."""
        epub_path = _make_epub(tmp_path)
        output_dir = tmp_path / "output"
        candidate = _make_candidate("Title Match", "Author", 0.9)

        provider = MagicMock()
        provider.search_by_isbn.return_value = []
        provider.search_by_title_author.return_value = [candidate]

        review = MagicMock()
        review.review.return_value = candidate.metadata

        result = match_one(epub_path, provider, review, output_dir)

        assert result.status == "matched"
        provider.search_by_title_author.assert_called_once()

    def test_match_one_returns_error_on_write_failure(self, tmp_path: Path) -> None:
        """match_one returns status='error' when apply_metadata_safely fails."""
        epub_path = _make_epub(tmp_path)
        output_dir = tmp_path / "output"
        candidate = _make_candidate("Title", "Author", 0.95)

        provider = MagicMock()
        provider.search_by_isbn.return_value = []
        provider.search_by_title_author.return_value = [candidate]

        review = MagicMock()
        review.review.return_value = candidate.metadata

        with patch("bookery.core.pipeline.apply_metadata_safely") as mock_write:
            from bookery.core.pipeline import WriteResult
            mock_write.return_value = WriteResult(
                path=None, success=False, error="Disk full",
            )
            result = match_one(epub_path, provider, review, output_dir)

        assert result.status == "error"
        assert "Disk full" in result.error
