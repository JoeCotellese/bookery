# ABOUTME: Integration tests for the web collection create/edit form flow (#252, #253).
# ABOUTME: Covers GET new, POST create/edit, and the non-persisting query preview route.

import html
import sqlite3

from bookery.collections import CollectionQueryError
from tests.web.conftest import make_book


def _collection(
    collection_id: int = 1,
    name: str = "Sci-Fi",
    description: str | None = None,
    query: str | None = None,
) -> dict[str, object]:
    """Build a collection dict shaped like the catalog return value."""
    return {
        "id": collection_id,
        "name": name,
        "description": description,
        "query": query,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }


class TestNewForm:
    def test_get_new_full_page(self, mock_catalog, client):
        html = client.get("/collections/new").data.decode()
        assert "New collection" in html
        assert 'name="name"' in html
        assert 'name="query"' in html
        # Full page carries the site chrome (base template).
        assert "Skip to main content" in html

    def test_get_new_htmx_partial(self, mock_catalog, client):
        resp = client.get("/collections/new", headers={"HX-Request": "true"})
        html = resp.data.decode()
        assert 'name="name"' in html
        # Partial omits the full-page chrome.
        assert "Skip to main content" not in html

    def test_get_new_prefills_query(self, mock_catalog, client):
        html = client.get(
            "/collections/new", query_string={"query": 'genre:"Science Fiction"'}
        ).data.decode()
        assert 'genre:"Science Fiction"' in html

    def test_form_has_preview_button_and_live_region(self, mock_catalog, client):
        html = client.get("/collections/new").data.decode()
        # Explicit, non-debounced trigger that posts the query to the preview route.
        assert 'hx-post="/collections/preview"' in html
        assert "Preview matches" in html
        # Results land in an aria-live region so screen readers announce them.
        assert 'id="collection-preview"' in html
        assert 'aria-live="polite"' in html


class TestCreate:
    def test_create_with_valid_query_redirects_to_detail(self, mock_catalog, client):
        mock_catalog.get_collection_by_name.return_value = None
        mock_catalog.create_collection.return_value = 7

        resp = client.post(
            "/collections/create",
            data={"name": "Sci-Fi", "query": 'genre:"Science Fiction"'},
            headers={"HX-Request": "true"},
        )

        assert resp.headers.get("HX-Redirect") == "/collections/7"
        _, kwargs = mock_catalog.create_collection.call_args
        assert kwargs.get("query") == 'genre:"Science Fiction"'

    def test_create_static_blank_query(self, mock_catalog, client):
        mock_catalog.get_collection_by_name.return_value = None
        mock_catalog.create_collection.return_value = 3

        resp = client.post(
            "/collections/create",
            data={"name": "Favorites", "description": "Hand-picked", "query": ""},
            headers={"HX-Request": "true"},
        )

        assert resp.headers.get("HX-Redirect") == "/collections/3"
        _, kwargs = mock_catalog.create_collection.call_args
        assert kwargs.get("query") is None

    def test_blank_name_inline_error_no_create(self, mock_catalog, client):
        mock_catalog.get_collection_by_name.return_value = None

        resp = client.post(
            "/collections/create",
            data={"name": "  ", "query": ""},
            headers={"HX-Request": "true"},
        )

        assert resp.status_code == 200
        assert "HX-Redirect" not in resp.headers
        assert "required" in resp.data.decode().lower()
        mock_catalog.create_collection.assert_not_called()

    def test_duplicate_name_precheck_inline_error(self, mock_catalog, client):
        mock_catalog.get_collection_by_name.return_value = _collection(name="Sci-Fi")

        resp = client.post(
            "/collections/create",
            data={"name": "Sci-Fi", "query": ""},
            headers={"HX-Request": "true"},
        )

        assert resp.status_code == 200
        assert "already exists" in resp.data.decode()
        mock_catalog.create_collection.assert_not_called()

    def test_duplicate_name_integrity_error_inline(self, mock_catalog, client):
        # Pre-check misses (race), but the DB UNIQUE constraint catches it.
        mock_catalog.get_collection_by_name.return_value = None
        mock_catalog.create_collection.side_effect = sqlite3.IntegrityError(
            "UNIQUE constraint failed: collections.name"
        )

        resp = client.post(
            "/collections/create",
            data={"name": "Sci-Fi", "query": ""},
            headers={"HX-Request": "true"},
        )

        assert resp.status_code == 200
        assert "already exists" in resp.data.decode()

    def test_invalid_query_inline_alert_no_create(self, mock_catalog, client):
        mock_catalog.get_collection_by_name.return_value = None

        resp = client.post(
            "/collections/create",
            data={"name": "Broken", "query": "notafield:value"},
            headers={"HX-Request": "true"},
        )

        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'role="alert"' in html
        # The textarea value is preserved for correction.
        assert "notafield:value" in html
        mock_catalog.create_collection.assert_not_called()


class TestEditForm:
    def test_get_edit_prefilled(self, mock_catalog, client):
        mock_catalog.get_collection_by_id.return_value = _collection(
            collection_id=4, name="Sci-Fi", description="Best of", query="series:Dune"
        )

        html = client.get("/collections/4/edit").data.decode()

        assert "Edit collection" in html
        assert 'value="Sci-Fi"' in html
        assert "Best of" in html
        assert "series:Dune" in html

    def test_get_edit_404_when_missing(self, mock_catalog, client):
        mock_catalog.get_collection_by_id.return_value = None
        assert client.get("/collections/999/edit").status_code == 404

    def test_post_edit_persists_name_and_description(self, mock_catalog, client):
        mock_catalog.get_collection_by_id.return_value = _collection(
            collection_id=4, name="Old", description="Old desc", query=None
        )
        mock_catalog.get_collection_by_name.return_value = None

        resp = client.post(
            "/collections/4/edit",
            data={"name": "New", "description": "New desc", "query": ""},
            headers={"HX-Request": "true"},
        )

        assert resp.headers.get("HX-Redirect") == "/collections/4"
        mock_catalog.rename_collection.assert_called_once_with(4, "New")
        mock_catalog.set_collection_description.assert_called_once_with(4, "New desc")

    def test_post_edit_rule_based_reset_applies_query(self, mock_catalog, client):
        mock_catalog.get_collection_by_id.return_value = _collection(
            collection_id=4, name="Sci-Fi", query="series:Dune"
        )
        mock_catalog.get_collection_by_name.return_value = None

        resp = client.post(
            "/collections/4/edit",
            data={"name": "Sci-Fi", "query": 'genre:"Science Fiction"'},
            headers={"HX-Request": "true"},
        )

        assert resp.headers.get("HX-Redirect") == "/collections/4"
        mock_catalog.set_collection_query.assert_called_once_with(
            4, 'genre:"Science Fiction"'
        )

    def test_post_edit_static_query_change_is_deferred(self, mock_catalog, client):
        # Static -> rule is a destructive transition handled in PR 4; this PR
        # must not silently convert it.
        mock_catalog.get_collection_by_id.return_value = _collection(
            collection_id=4, name="Favorites", query=None
        )
        mock_catalog.get_collection_by_name.return_value = None

        resp = client.post(
            "/collections/4/edit",
            data={"name": "Favorites", "query": 'genre:"Science Fiction"'},
            headers={"HX-Request": "true"},
        )

        assert resp.headers.get("HX-Redirect") == "/collections/4"
        mock_catalog.set_collection_query.assert_not_called()

    def test_post_edit_invalid_query_inline_alert(self, mock_catalog, client):
        mock_catalog.get_collection_by_id.return_value = _collection(
            collection_id=4, name="Sci-Fi", query="series:Dune"
        )
        mock_catalog.get_collection_by_name.return_value = None

        resp = client.post(
            "/collections/4/edit",
            data={"name": "Sci-Fi", "query": "notafield:value"},
            headers={"HX-Request": "true"},
        )

        assert resp.status_code == 200
        assert 'role="alert"' in resp.data.decode()
        mock_catalog.set_collection_query.assert_not_called()


class TestListAndDetailAffordances:
    def test_list_has_new_collection_button(self, mock_catalog, client):
        mock_catalog.list_collections.return_value = []
        html = client.get("/collections").data.decode()
        assert "/collections/new" in html
        assert "New collection" in html

    def test_detail_has_edit_affordance(self, mock_catalog, client):
        mock_catalog.get_collection_by_id.return_value = _collection(collection_id=4)
        mock_catalog.get_collection_books.return_value = []
        html = client.get("/collections/4").data.decode()
        assert "/collections/4/edit" in html


class TestPreview:
    """POST /collections/preview — non-persisting match preview (#253)."""

    def test_valid_query_renders_count_and_sample(self, mock_catalog, client):
        mock_catalog.resolve_query_preview.return_value = (
            2,
            [make_book(1, title="Apex"), make_book(2, title="The Border")],
        )

        resp = client.post(
            "/collections/preview",
            data={"query": 'genre:"Science Fiction"'},
            headers={"HX-Request": "true"},
        )

        assert resp.status_code == 200
        html = resp.data.decode()
        assert "Matches: 2" in html
        assert "Apex" in html
        assert "The Border" in html
        mock_catalog.resolve_query_preview.assert_called_once()

    def test_broad_query_caps_sample_but_shows_true_total(self, mock_catalog, client):
        sample = [make_book(i, title=f"Book {i}") for i in range(50)]
        mock_catalog.resolve_query_preview.return_value = (312, sample)

        html = client.post(
            "/collections/preview",
            data={"query": "year:>0"},
            headers={"HX-Request": "true"},
        ).data.decode()

        assert "Matches: 312" in html
        assert "showing first 50" in html

    def test_zero_match_shows_empty_state_not_error(self, mock_catalog, client):
        mock_catalog.resolve_query_preview.return_value = (0, [])

        resp = client.post(
            "/collections/preview",
            data={"query": 'genre:"Nonexistent"'},
            headers={"HX-Request": "true"},
        )

        assert resp.status_code == 200
        html = resp.data.decode()
        assert "0 books match" in html
        assert 'role="alert"' not in html

    def test_invalid_query_inline_alert_http_200(self, mock_catalog, client):
        mock_catalog.resolve_query_preview.side_effect = CollectionQueryError(
            "Unknown field 'notafield'."
        )

        resp = client.post(
            "/collections/preview",
            data={"query": "notafield:value"},
            headers={"HX-Request": "true"},
        )

        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'role="alert"' in html
        assert "notafield" in html

    def test_blank_query_shows_static_notice(self, mock_catalog, client):
        resp = client.post(
            "/collections/preview",
            data={"query": "   "},
            headers={"HX-Request": "true"},
        )

        assert resp.status_code == 200
        html = resp.data.decode()
        assert "Static collection" in html
        mock_catalog.resolve_query_preview.assert_not_called()


class TestQueryAppend:
    """POST /collections/query/append — append-only query builder (#254)."""

    @staticmethod
    def _textarea_body(response) -> str:
        """The textarea's text content, HTML-unescaped.

        Assert against this rather than the raw response so the static
        ``placeholder`` example (which contains its own ``field:"value"``
        sample) can't produce a false-positive substring match.
        """
        raw = response.data.decode()
        body = raw.split(">", 1)[1].rsplit("</textarea>", 1)[0]
        return html.unescape(body)

    def test_first_clause_has_no_leading_operator(self, mock_catalog, client):
        resp = client.post(
            "/collections/query/append",
            data={"field": "series", "value": "Dune", "query": ""},
            headers={"HX-Request": "true"},
        )

        assert resp.status_code == 200
        # Response is the re-rendered textarea (the swap target).
        assert 'name="query"' in resp.data.decode()
        assert self._textarea_body(resp) == "series:Dune"

    def test_appends_onto_existing_query_with_and(self, mock_catalog, client):
        resp = client.post(
            "/collections/query/append",
            data={"field": "author", "value": "Frank Herbert", "query": "series:Dune"},
            headers={"HX-Request": "true"},
        )

        assert resp.status_code == 200
        assert self._textarea_body(resp) == 'series:Dune AND author:"Frank Herbert"'

    def test_value_with_spaces_is_quoted(self, mock_catalog, client):
        resp = client.post(
            "/collections/query/append",
            data={"field": "publisher", "value": "Tor Books", "query": ""},
            headers={"HX-Request": "true"},
        )

        assert self._textarea_body(resp) == 'publisher:"Tor Books"'

    def test_unknown_field_is_rejected(self, mock_catalog, client):
        resp = client.post(
            "/collections/query/append",
            data={"field": "notafield", "value": "x", "query": ""},
            headers={"HX-Request": "true"},
        )

        assert resp.status_code == 400

    def test_blank_value_is_rejected(self, mock_catalog, client):
        resp = client.post(
            "/collections/query/append",
            data={"field": "series", "value": "   ", "query": ""},
            headers={"HX-Request": "true"},
        )

        assert resp.status_code == 400
