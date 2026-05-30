# ABOUTME: Integration tests for the web collection create/edit form flow (#252).
# ABOUTME: Covers GET new, POST create (valid/static/blank/dup/invalid), and edit prefill+save.

import sqlite3


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
