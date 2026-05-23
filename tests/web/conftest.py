# ABOUTME: Shared fixtures for tests/web — Flask test client + BookRecord builders.
# ABOUTME: Mirrors tests/unit/test_web_app.py helpers without coupling to that file.

from pathlib import Path
from unittest.mock import Mock

import pytest

from bookery.db.mapping import BookRecord
from bookery.metadata.types import BookMetadata
from bookery.web import create_app


def make_book(
    book_id: int = 1,
    title: str = "Test Book",
    authors: list[str] | None = None,
    author_sort: str | None = None,
    isbn: str | None = None,
    language: str | None = None,
    publisher: str | None = None,
    source_path: Path = Path("/books/test.epub"),
    output_path: Path | None = None,
    description: str | None = None,
    series: str | None = None,
    series_index: float | None = None,
    file_hash: str = "abc123",
    date_added: str = "2026-01-01",
    date_modified: str = "2026-01-02",
) -> BookRecord:
    """Build a BookRecord for web template tests."""
    return BookRecord(
        id=book_id,
        metadata=BookMetadata(
            title=title,
            authors=authors or ["Unknown"],
            author_sort=author_sort or (authors[0] if authors else "Unknown"),
            isbn=isbn,
            language=language,
            publisher=publisher,
            description=description,
            series=series,
            series_index=series_index,
        ),
        file_hash=file_hash,
        source_path=source_path,
        output_path=output_path,
        date_added=date_added,
        date_modified=date_modified,
    )


@pytest.fixture
def mock_catalog():
    """Mock LibraryCatalog with sensible defaults."""
    catalog = Mock()
    catalog.list_all_by_author.return_value = []
    catalog.search.return_value = []
    catalog.get_by_id.return_value = None
    catalog.get_tags_for_book.return_value = []
    catalog.get_genres_for_book.return_value = []
    return catalog


@pytest.fixture
def app(mock_catalog):
    """Flask app wired to the mock catalog."""
    app = create_app(mock_catalog)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()
