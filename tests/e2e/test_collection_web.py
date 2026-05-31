# ABOUTME: E2E tests for the web collection create + query-preview flow on a real catalog.
# ABOUTME: Drives create_app over a temp SQLite DB through the Flask test client.

import html
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


class TestQueryBuilderEndToEnd:
    def test_compose_two_clauses_preview_save_lands_on_detail(
        self, client, catalog: LibraryCatalog
    ) -> None:
        """Build a rule via the append composer, preview it, save, and land on a
        detail page showing the rule and the matched book."""
        # First condition: series:Dune (no leading operator).
        first = client.post(
            "/collections/query/append",
            data={"field": "series", "value": "Dune", "query": ""},
            headers={"HX-Request": "true"},
        )
        assert first.status_code == 200
        assert "series:Dune" in html.unescape(first.data.decode())

        # Second condition appends with AND and quotes the multi-word value.
        second = client.post(
            "/collections/query/append",
            data={"field": "author", "value": "Frank Herbert", "query": "series:Dune"},
            headers={"HX-Request": "true"},
        )
        composed = html.unescape(
            second.data.decode().split(">", 1)[1].rsplit("</textarea>", 1)[0]
        )
        assert composed == 'series:Dune AND author:"Frank Herbert"'

        # Preview the composed query — it matches the seeded Dune book.
        preview = client.post(
            "/collections/preview",
            data={"query": composed},
            headers={"HX-Request": "true"},
        )
        assert preview.status_code == 200
        preview_html = preview.data.decode()
        assert "Matches: 1" in preview_html
        assert "Dune" in preview_html

        # Saving the composed query creates a rule-based collection.
        created = client.post(
            "/collections/create",
            data={"name": "Herbert's Dune", "query": composed},
            headers={"HX-Request": "true"},
        )
        target = created.headers["HX-Redirect"]

        detail = html.unescape(client.get(target).data.decode())
        assert "Herbert's Dune" in detail
        assert 'series:Dune AND author:"Frank Herbert"' in detail
        assert "Dune" in detail  # the matched book title

    def test_append_rejects_unknown_field(
        self, client, catalog: LibraryCatalog
    ) -> None:
        """The composer never emits an off-whitelist field — the route 400s."""
        resp = client.post(
            "/collections/query/append",
            data={"field": "evil", "value": "x", "query": ""},
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 400


class TestConversionGateEndToEnd:
    """Full edit-form conversions on a real catalog: warn, confirm, mutate."""

    def test_static_to_rule_warns_then_confirm_drops_handpicked(
        self, client, catalog: LibraryCatalog
    ) -> None:
        """Hand-picked books trigger a discard warning; confirming converts the
        collection to rule-based and drops the manual membership."""
        # A static collection holding the seeded Dune book (id 1) by hand.
        cid = catalog.create_collection("Favorites")
        catalog.add_books_to_collection(cid, [1])

        # First edit: set a rule. The hand-picked book is at stake, so the form
        # comes back with the discard warning and persists nothing.
        warn = client.post(
            f"/collections/{cid}/edit",
            data={"name": "Favorites", "query": "series:Dune"},
            headers={"HX-Request": "true"},
        )
        assert warn.status_code == 200
        assert "HX-Redirect" not in warn.headers
        assert "discards the 1 hand-picked book" in warn.data.decode()
        # Still static, still holding the manual member.
        before = catalog.get_collection_by_id(cid)
        assert before is not None and before["query"] is None
        assert catalog.resolve_collection_member_ids(cid) == [1]

        # Second edit with confirm=1 executes the conversion.
        done = client.post(
            f"/collections/{cid}/edit",
            data={"name": "Favorites", "query": "series:Dune", "confirm": "1"},
            headers={"HX-Request": "true"},
        )
        assert done.headers["HX-Redirect"] == f"/collections/{cid}"

        collection = catalog.get_collection_by_id(cid)
        assert collection is not None and collection["query"] == "series:Dune"
        # Membership is now rule-derived (still matches Dune), and the detail page
        # shows the rule with no manual "Remove" affordance.
        detail = client.get(f"/collections/{cid}").data.decode()
        assert "series:Dune" in detail
        assert "Dune" in detail
        assert "Remove" not in detail

    def test_rule_to_static_warns_then_confirm_snapshots_members(
        self, client, catalog: LibraryCatalog
    ) -> None:
        """Clearing a rule snapshots live matches as a static list; confirming
        makes manual removal available again."""
        cid = catalog.create_collection("Sci-Fi", query="series:Dune")

        # First edit: clear the rule. Always warns, since the kind change is
        # meaningful, and persists nothing yet.
        warn = client.post(
            f"/collections/{cid}/edit",
            data={"name": "Sci-Fi", "query": ""},
            headers={"HX-Request": "true"},
        )
        assert warn.status_code == 200
        assert "HX-Redirect" not in warn.headers
        assert "snapshots the 1 currently-matching book" in warn.data.decode()
        before = catalog.get_collection_by_id(cid)
        assert before is not None and before["query"] == "series:Dune"

        # Confirm: the rule is cleared and the matched book is snapshotted static.
        done = client.post(
            f"/collections/{cid}/edit",
            data={"name": "Sci-Fi", "query": "", "confirm": "1"},
            headers={"HX-Request": "true"},
        )
        assert done.headers["HX-Redirect"] == f"/collections/{cid}"

        collection = catalog.get_collection_by_id(cid)
        assert collection is not None and collection["query"] is None
        assert catalog.resolve_collection_member_ids(cid) == [1]
        # Manual removal is available again on a static collection's detail page.
        detail = client.get(f"/collections/{cid}").data.decode()
        assert "Remove" in detail

        # And the snapshot is genuinely static: removing the book sticks.
        catalog.remove_books_from_collection(cid, [1])
        assert catalog.resolve_collection_member_ids(cid) == []
