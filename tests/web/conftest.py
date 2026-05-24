# ABOUTME: Shared fixtures for tests/web — Flask test client + BookRecord builders.
# ABOUTME: Mirrors tests/unit/test_web_app.py helpers without coupling to that file.

from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import Mock

import pytest

from bookery.db.mapping import BookRecord
from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.types import BookMetadata
from bookery.web import create_app


@dataclass
class FakeProvider:
    """Test double matching the MetadataProvider protocol.

    Each method records the call args and returns the queued list/value so
    tests can assert which dispatch path the route used.
    """

    name: str
    by_isbn: list[MetadataCandidate] = field(default_factory=list)
    by_title_author: list[MetadataCandidate] = field(default_factory=list)
    by_url: MetadataCandidate | None = None
    isbn_calls: list[str] = field(default_factory=list)
    title_author_calls: list[tuple[str, str | None]] = field(default_factory=list)
    url_calls: list[str] = field(default_factory=list)

    def search_by_isbn(self, isbn: str) -> list[MetadataCandidate]:
        self.isbn_calls.append(isbn)
        return list(self.by_isbn)

    def search_by_title_author(
        self, title: str, author: str | None = None
    ) -> list[MetadataCandidate]:
        self.title_author_calls.append((title, author))
        return list(self.by_title_author)

    def lookup_by_url(self, url: str) -> MetadataCandidate | None:
        self.url_calls.append(url)
        return self.by_url


def make_candidate(
    title: str = "Sample",
    authors: list[str] | None = None,
    isbn: str | None = None,
    publisher: str | None = None,
    published_date: str | None = None,
    confidence: float = 0.5,
    source: str = "fake",
    source_id: str = "fake:1",
) -> MetadataCandidate:
    """Build a MetadataCandidate for web tests."""
    return MetadataCandidate(
        metadata=BookMetadata(
            title=title,
            authors=authors or ["Author"],
            isbn=isbn,
            publisher=publisher,
            published_date=published_date,
        ),
        confidence=confidence,
        source=source,
        source_id=source_id,
    )


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
    metadata_matched_at: str | None = None,
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
        metadata_matched_at=metadata_matched_at,
    )


@pytest.fixture
def mock_catalog():
    """Mock LibraryCatalog with sensible defaults."""
    catalog = Mock()
    catalog.list_all_by_author.return_value = []
    catalog.search.return_value = []
    catalog.browse.return_value = ([], 0)
    catalog.get_by_id.return_value = None
    catalog.get_tags_for_book.return_value = []
    catalog.get_genres_for_book.return_value = []
    return catalog


@pytest.fixture
def providers():
    """Default providers fixture: empty dict (tests override as needed)."""
    return {}


@pytest.fixture
def app(mock_catalog, providers):
    """Flask app wired to the mock catalog and provider registry."""
    app = create_app(mock_catalog, providers=providers)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()
