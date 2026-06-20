# ABOUTME: Integration tests for the collection delete-confirmation modal (issue #256).
# ABOUTME: Covers the confirm GET partial, the detail-page trigger, and confirmed delete.

import re


def _collection(cid=1, name="Favorites", query=None):
    return {"id": cid, "name": name, "description": None, "query": query}


class TestCollectionDeleteConfirm:
    def test_confirm_renders_dialog_with_reassurance(self, mock_catalog, client):
        mock_catalog.get_collection_by_id.return_value = _collection(1, "Favorites")

        html = client.get("/collections/1/delete").data.decode()

        assert 'role="dialog"' in html
        assert "aria-modal" in html
        assert "Favorites" in html
        assert "Your books are not deleted" in html

    def test_confirm_missing_collection_404(self, mock_catalog, client):
        mock_catalog.get_collection_by_id.return_value = None
        assert client.get("/collections/99/delete").status_code == 404

    def test_detail_page_has_delete_trigger(self, mock_catalog, client):
        mock_catalog.get_collection_by_id.return_value = _collection(1, "Favorites")
        mock_catalog.get_collection_books.return_value = []

        html = client.get("/collections/1").data.decode()

        # A Delete control that opens the confirm modal via htmx GET.
        trigger = re.search(r"hx-get=\"[^\"]*/collections/1/delete\"", html)
        assert trigger, "Collection detail must expose a Delete trigger"

    def test_confirmed_delete_removes_row_and_redirects(self, mock_catalog, client):
        mock_catalog.get_collection_by_id.return_value = _collection(1, "Favorites")

        resp = client.post("/collections/1/delete", follow_redirects=False)

        assert resp.status_code in (302, 303)
        mock_catalog.delete_collection.assert_called_once_with(1)
