# ABOUTME: Unit tests for the Flask web UI app factory and routes.
# ABOUTME: Tests use mock catalogs to avoid database dependencies.

from pathlib import Path
from unittest.mock import Mock

import pytest
from flask import Flask

from bookery.db.mapping import BookRecord
from bookery.metadata.types import BookMetadata
from bookery.web import create_app


def _make_book(
    book_id: int,
    title: str = "Test Book",
    authors: list[str] | None = None,
    author_sort: str | None = None,
    isbn: str | None = None,
    language: str | None = None,
    publisher: str | None = None,
    output_path: Path | None = None,
    description: str | None = None,
    series: str | None = None,
    series_index: float | None = None,
) -> BookRecord:
    """Helper to create a BookRecord for tests."""
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
        file_hash="abc123",
        source_path=Path("/books/test.epub"),
        output_path=output_path,
        date_added="2026-01-01",
        date_modified="2026-01-01",
    )


@pytest.fixture
def mock_catalog():
    """A mock LibraryCatalog with default empty returns."""
    catalog = Mock()
    catalog.list_all_by_author.return_value = []
    catalog.search.return_value = []
    catalog.get_by_id.return_value = None
    catalog.get_tags_for_book.return_value = []
    catalog.get_genres_for_book.return_value = []
    return catalog


@pytest.fixture
def app(mock_catalog):
    """Create a test Flask app with mock catalog."""
    app = create_app(mock_catalog)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


# --- Cycle 1: App Factory + Root Redirect ---


class TestAppFactory:
    def test_create_app_returns_flask_instance(self, app):
        assert isinstance(app, Flask)

    def test_root_redirects_to_books(self, client):
        response = client.get("/")
        assert response.status_code == 302
        assert response.headers["Location"] == "/books"


# --- Cycle 2: Book List ---


class TestBookList:
    def test_books_empty_library_shows_empty_state(self, client):
        response = client.get("/books")
        assert response.status_code == 200
        assert b"Your library is empty" in response.data

    def test_books_lists_all_books_sorted_by_author(self, mock_catalog, client):
        book_a = _make_book(1, title="Zebra", authors=["Adams, John"], author_sort="Adams, John")
        book_b = _make_book(2, title="Apple", authors=["Brown, Dan"], author_sort="Brown, Dan")
        mock_catalog.list_all_by_author.return_value = [book_a, book_b]

        response = client.get("/books")
        html = response.data.decode()
        # Adams should appear before Brown in the rendered output
        assert html.index("Adams, John") < html.index("Brown, Dan")

    def test_books_table_shows_enriched_badge(self, mock_catalog, client):
        enriched = _make_book(1, title="Enriched", output_path=Path("/out/enriched.epub"))
        plain = _make_book(2, title="Plain")
        mock_catalog.list_all_by_author.return_value = [enriched, plain]

        response = client.get("/books")
        html = response.data.decode()
        # There should be exactly one checkmark for the enriched book
        assert html.count("&#10003;") == 1

    def test_books_table_columns(self, mock_catalog, client):
        book = _make_book(
            1,
            title="The Great Gatsby",
            authors=["Fitzgerald, F. Scott"],
            isbn="9780743273565",
            language="en",
            publisher="Scribner",
        )
        mock_catalog.list_all_by_author.return_value = [book]

        response = client.get("/books")
        html = response.data.decode()
        assert "The Great Gatsby" in html
        assert "Fitzgerald, F. Scott" in html
        assert "9780743273565" in html
        assert "en" in html
        assert "Scribner" in html


# --- Cycle 3: Book Detail ---


class TestBookDetail:
    def test_book_detail_shows_metadata(self, mock_catalog, client):
        book = _make_book(
            1,
            title="Dune",
            authors=["Herbert, Frank"],
            isbn="9780441172719",
            language="en",
            publisher="Ace Books",
            description="A science fiction masterpiece.",
            series="Dune Chronicles",
            series_index=1.0,
        )
        mock_catalog.get_by_id.return_value = book

        response = client.get("/books/1")
        html = response.data.decode()
        assert response.status_code == 200
        assert "Dune" in html
        assert "Herbert, Frank" in html
        assert "9780441172719" in html
        assert "en" in html
        assert "Ace Books" in html
        assert "A science fiction masterpiece." in html
        assert "Dune Chronicles" in html

    def test_book_detail_shows_tags_and_genres(self, mock_catalog, client):
        book = _make_book(1, title="Tagged Book")
        mock_catalog.get_by_id.return_value = book
        mock_catalog.get_tags_for_book.return_value = ["sci-fi", "classic"]
        mock_catalog.get_genres_for_book.return_value = [
            ("Science Fiction", True),
            ("Adventure", False),
        ]

        response = client.get("/books/1")
        html = response.data.decode()
        assert "sci-fi" in html
        assert "classic" in html
        assert "Science Fiction" in html
        assert "Adventure" in html

    def test_book_detail_404_for_missing_book(self, client):
        response = client.get("/books/999")
        assert response.status_code == 404


# --- Cycle 4: Search with htmx ---


class TestSearch:
    def test_search_returns_matching_books(self, mock_catalog, client):
        book = _make_book(1, title="The Rose Garden")
        mock_catalog.search.return_value = [book]

        response = client.get("/books?q=rose")
        html = response.data.decode()
        assert response.status_code == 200
        assert "The Rose Garden" in html
        mock_catalog.search.assert_called_once_with("rose")

    def test_search_no_results_message(self, mock_catalog, client):
        mock_catalog.search.return_value = []

        response = client.get("/books?q=zzzzz")
        html = response.data.decode()
        assert "No books matching &#39;zzzzz&#39;" in html or "No books matching 'zzzzz'" in html

    def test_htmx_request_returns_partial_only(self, mock_catalog, client):
        mock_catalog.search.return_value = []

        response = client.get("/books?q=test", headers={"HX-Request": "true"})
        html = response.data.decode()
        assert "<html" not in html
        assert "<head" not in html

    def test_non_htmx_search_returns_full_page(self, mock_catalog, client):
        mock_catalog.search.return_value = []

        response = client.get("/books?q=test")
        html = response.data.decode()
        assert "<html" in html
