# ABOUTME: Shared pytest fixtures for Bookery tests.
# ABOUTME: Provides sample EPUB files (valid and corrupt) for testing.

from pathlib import Path

import pytest
from ebooklib import epub


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to the test fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_epub(tmp_path: Path) -> Path:
    """Create a minimal valid EPUB file with known metadata."""
    book = epub.EpubBook()

    book.set_identifier("test-isbn-978-0-123456-47-2")
    book.set_title("The Name of the Rose")
    book.set_language("en")
    book.add_author("Umberto Eco")

    book.add_metadata("DC", "publisher", "Harcourt")
    book.add_metadata("DC", "description", "A mystery set in a medieval monastery.")

    # Add a minimal chapter so the EPUB is structurally valid
    chapter = epub.EpubHtml(title="Chapter 1", file_name="chap01.xhtml", lang="en")
    chapter.content = b"<html><body><h1>Chapter 1</h1><p>Content.</p></body></html>"
    book.add_item(chapter)

    # Add navigation
    book.toc = [epub.Link("chap01.xhtml", "Chapter 1", "chap01")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]

    filepath = tmp_path / "name_of_the_rose.epub"
    epub.write_epub(str(filepath), book)
    return filepath


@pytest.fixture
def corrupt_epub(tmp_path: Path) -> Path:
    """Create a corrupt file that is not a valid EPUB."""
    filepath = tmp_path / "corrupt.epub"
    filepath.write_text("this is not a valid epub file")
    return filepath


@pytest.fixture
def minimal_epub(tmp_path: Path) -> Path:
    """Create an EPUB with minimal metadata (only title)."""
    book = epub.EpubBook()
    book.set_identifier("minimal-id")
    book.set_title("Untitled Book")
    book.set_language("en")

    chapter = epub.EpubHtml(title="Content", file_name="content.xhtml", lang="en")
    chapter.content = b"<html><body><p>Minimal content.</p></body></html>"
    book.add_item(chapter)

    book.toc = [epub.Link("content.xhtml", "Content", "content")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]

    filepath = tmp_path / "minimal.epub"
    epub.write_epub(str(filepath), book)
    return filepath
