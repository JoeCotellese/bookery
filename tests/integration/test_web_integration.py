# ABOUTME: Integration tests for the Flask web UI with a real SQLite database.
# ABOUTME: Validates the full stack from HTTP request through catalog to rendered HTML.

from pathlib import Path

import pytest

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata
from bookery.web import create_app


@pytest.fixture
def catalog(tmp_path):
    """Create a real LibraryCatalog backed by a temporary database."""
    db_path = tmp_path / "test.db"
    conn = open_library(db_path)
    cat = LibraryCatalog(conn)
    yield cat
    conn.close()


@pytest.fixture
def populated_catalog(catalog):
    """Catalog with two books for testing."""
    catalog.add_book(
        BookMetadata(
            title="Dune",
            authors=["Herbert, Frank"],
            author_sort="Herbert, Frank",
            isbn="9780441172719",
            language="en",
            publisher="Ace Books",
            description="A desert planet epic.",
            source_path=Path("/books/dune.epub"),
        ),
        file_hash="hash_dune",
    )
    catalog.add_book(
        BookMetadata(
            title="Foundation",
            authors=["Asimov, Isaac"],
            author_sort="Asimov, Isaac",
            isbn="9780553293357",
            language="en",
            publisher="Bantam",
            description="The fall of a galactic empire.",
            source_path=Path("/books/foundation.epub"),
        ),
        file_hash="hash_foundation",
    )
    return catalog


@pytest.fixture
def client(populated_catalog):
    """Flask test client wired to the populated catalog."""
    app = create_app(populated_catalog)
    app.config["TESTING"] = True
    return app.test_client()


class TestWebIntegration:
    def test_book_list_shows_all_books(self, client):
        response = client.get("/books")
        html = response.data.decode()
        assert response.status_code == 200
        assert "Dune" in html
        assert "Foundation" in html

    def test_book_list_sorted_by_author(self, client):
        response = client.get("/books")
        html = response.data.decode()
        # Asimov comes before Herbert alphabetically
        assert html.index("Asimov, Isaac") < html.index("Herbert, Frank")

    def test_search_finds_matching_book(self, client):
        response = client.get("/books?q=dune")
        html = response.data.decode()
        assert "Dune" in html
        assert "Foundation" not in html

    def test_search_no_results(self, client):
        response = client.get("/books?q=nonexistent")
        html = response.data.decode()
        assert "No books matching" in html

    def test_book_detail_page(self, client):
        response = client.get("/books/1")
        html = response.data.decode()
        assert response.status_code == 200
        assert "Dune" in html
        assert "Herbert, Frank" in html
        assert "A desert planet epic." in html

    def test_detail_404_for_missing_book(self, client):
        response = client.get("/books/999")
        assert response.status_code == 404

    def test_empty_library(self, catalog):
        # Use the empty catalog (no books added)
        app = create_app(catalog)
        app.config["TESTING"] = True
        c = app.test_client()
        response = c.get("/books")
        html = response.data.decode()
        assert "Your library is empty" in html

    def test_edit_and_save_persists_changes(self, client):
        # Get the edit form
        response = client.get("/books/1/edit")
        assert response.status_code == 200
        assert "<form" in response.data.decode()

        # Save with updated title
        response = client.post(
            "/books/1/edit",
            data={
                "title": "Dune Messiah",
                "authors": "Herbert, Frank",
                "isbn": "9780441172719",
                "language": "en",
                "publisher": "Ace Books",
                "description": "A desert planet epic.",
                "series": "",
                "series_index": "",
            },
        )
        assert response.status_code == 200

        # Verify the detail page shows the updated title
        response = client.get("/books/1")
        html = response.data.decode()
        assert "Dune Messiah" in html

    def test_edit_cancel_preserves_original(self, client):
        # Load the edit form (read-only, no changes)
        response = client.get("/books/1/edit")
        assert response.status_code == 200

        # Without posting, go back to detail — title unchanged
        response = client.get("/books/1")
        html = response.data.decode()
        assert "Dune" in html

    def test_edit_title_validation(self, client):
        response = client.post(
            "/books/1/edit",
            data={
                "title": "",
                "authors": "Herbert, Frank",
                "isbn": "",
                "language": "",
                "publisher": "",
                "description": "",
                "series": "",
                "series_index": "",
            },
        )
        assert response.status_code == 400
        assert "Title is required" in response.data.decode()
