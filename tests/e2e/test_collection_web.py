# ABOUTME: E2E tests for the web collection create + query-preview flow on a real catalog.
# ABOUTME: Drives create_app over a temp SQLite DB through the Flask test client.

from pathlib import Path

import pytest

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata
from bookery.web import create_app


@pytest.fixture()
def catalog(tmp_path: Path) -> LibraryCatalog:
    """A real LibraryCatalog backed by a temporary database, with one book."""
    conn = open_library(tmp_path / "web_e2e.db")
    catalog = LibraryCatalog(conn)
    catalog.add_book(
        BookMetadata(
            title="Dune",
            authors=["Frank Herbert"],
            series="Dune",
            source_path=Path("/books/dune.epub"),
        ),
        file_hash="dune_hash",
    )
    return catalog


@pytest.fixture()
def client(catalog: LibraryCatalog):
    """Flask test client wired to the real catalog."""
    app = create_app(catalog)
    app.config["TESTING"] = True
    return app.test_client()


class TestCreateRuleCollectionEndToEnd:
    def test_create_rule_collection_lands_on_detail(
        self, client, catalog: LibraryCatalog
    ) -> None:
        """A valid rule persists a rule-based collection; the redirect target shows it."""
        resp = client.post(
            "/collections/create",
            data={"name": "Dune Saga", "query": "series:Dune"},
            headers={"HX-Request": "true"},
        )

        # Inline create returns an HX-Redirect to the new collection's detail page.
        target = resp.headers["HX-Redirect"]
        assert target.startswith("/collections/")

        # The row is persisted as rule-based (query stored, not static membership).
        collection = catalog.get_collection_by_name("Dune Saga")
        assert collection is not None
        assert collection["query"] == "series:Dune"

        # Following the redirect lands on the detail page, which surfaces the rule
        # and the live-matched book.
        detail = client.get(target).data.decode()
        assert "Dune Saga" in detail
        assert "series:Dune" in detail
        assert "Dune" in detail  # the matched book title

    def test_duplicate_name_inline_error_creates_no_second_row(
        self, client, catalog: LibraryCatalog
    ) -> None:
        """A duplicate (case-insensitive) name re-renders the form inline, no new row."""
        first = client.post(
            "/collections/create",
            data={"name": "Favorites", "query": ""},
            headers={"HX-Request": "true"},
        )
        assert first.headers.get("HX-Redirect", "").startswith("/collections/")

        second = client.post(
            "/collections/create",
            data={"name": "favorites", "query": ""},  # case-insensitive clash
            headers={"HX-Request": "true"},
        )

        assert second.status_code == 200
        assert "HX-Redirect" not in second.headers
        assert "already exists" in second.data.decode()

        # Only the original row exists.
        names = [c["name"] for c in catalog.list_collections()]
        assert names.count("Favorites") == 1
        assert len(names) == 1


class TestQueryPreviewEndToEnd:
    def test_empty_result_preview_then_save_lands_on_empty_detail(
        self, client, catalog: LibraryCatalog
    ) -> None:
        """A valid rule matching nothing previews "0 books", saves, and the
        detail page shows the rule-based empty state."""
        # Preview a valid query that matches no book in the seeded catalog.
        preview = client.post(
            "/collections/preview",
            data={"query": "series:Nonexistent"},
            headers={"HX-Request": "true"},
        )
        assert preview.status_code == 200
        preview_html = preview.data.decode()
        assert "0 books match" in preview_html
        assert 'role="alert"' not in preview_html  # zero matches is not an error
        # Preview must not have persisted anything.
        assert catalog.list_collections() == []

        # Saving the same query succeeds and redirects to the detail page.
        created = client.post(
            "/collections/create",
            data={"name": "Empty Rule", "query": "series:Nonexistent"},
            headers={"HX-Request": "true"},
        )
        target = created.headers["HX-Redirect"]

        detail = client.get(target).data.decode()
        assert "Empty Rule" in detail
        assert "No books match this rule yet." in detail
