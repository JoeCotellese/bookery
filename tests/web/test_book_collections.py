# ABOUTME: Integration tests for the book-detail Collections section (issue #256).
# ABOUTME: Covers add-to-static, rule-collection guards, membership list + remove.

import re

from tests.web.conftest import make_book


def _collection(cid, name, query=None):
    return {"id": cid, "name": name, "description": None, "query": query}


class TestBookDetailCollectionsSection:
    def test_detail_shows_collections_section(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)
        mock_catalog.get_collections_for_book.return_value = []
        mock_catalog.list_collections.return_value = [_collection(7, "Favorites")]

        html = client.get("/books/1").data.decode()

        assert "Collections" in html
        assert 'name="collection_id"' in html  # the add-to-collection select

    def test_select_lists_static_excludes_rule(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)
        mock_catalog.get_collections_for_book.return_value = []
        mock_catalog.list_collections.return_value = [
            _collection(7, "Favorites"),
            _collection(8, "Sci-Fi Rule", query="genre:scifi"),
        ]

        html = client.get("/books/1").data.decode()

        # The <select> offers the static collection but not the rule-based one.
        select = re.search(r"<select[^>]*name=\"collection_id\".*?</select>", html, re.DOTALL)
        assert select, "Add-to-collection select must render"
        assert "Favorites" in select.group(0)
        assert "Sci-Fi Rule" not in select.group(0)

    def test_membership_list_shows_remove_form(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)
        mock_catalog.get_collections_for_book.return_value = [_collection(7, "Favorites")]
        mock_catalog.list_collections.return_value = [_collection(7, "Favorites")]

        html = client.get("/books/1").data.decode()

        assert "Favorites" in html
        assert "/collections/7/remove-book/1" in html

    def test_quick_create_link_seeds_author_query(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1, authors=["Frank Herbert"])
        mock_catalog.get_collections_for_book.return_value = []
        mock_catalog.list_collections.return_value = []

        html = client.get("/books/1").data.decode()

        assert "/collections/new?query=" in html
        assert "Frank" in html and "Herbert" in html


class TestAddBookToCollection:
    def test_add_to_static_calls_catalog(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)
        mock_catalog.get_collection_by_id.return_value = _collection(7, "Favorites")
        mock_catalog.get_collections_for_book.return_value = [_collection(7, "Favorites")]
        mock_catalog.list_collections.return_value = [_collection(7, "Favorites")]

        resp = client.post("/books/1/add-to-collection", data={"collection_id": "7"})

        assert resp.status_code == 200
        mock_catalog.add_books_to_collection.assert_called_once_with(7, [1])
        # Outer-swap returns the refreshed membership section.
        assert "Favorites" in resp.data.decode()

    def test_add_to_rule_collection_rejected(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)
        mock_catalog.get_collection_by_id.return_value = _collection(
            8, "Sci-Fi", query="genre:scifi"
        )
        mock_catalog.get_collections_for_book.return_value = []
        mock_catalog.list_collections.return_value = [
            _collection(8, "Sci-Fi", query="genre:scifi")
        ]

        resp = client.post("/books/1/add-to-collection", data={"collection_id": "8"})

        assert resp.status_code == 200
        mock_catalog.add_books_to_collection.assert_not_called()

    def test_add_missing_book_404(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = None
        resp = client.post("/books/99/add-to-collection", data={"collection_id": "7"})
        assert resp.status_code == 404


class TestCollectionAddBooksGuard:
    def test_add_books_to_rule_collection_rejected(self, mock_catalog, client):
        mock_catalog.get_collection_by_id.return_value = _collection(
            8, "Sci-Fi", query="genre:scifi"
        )

        resp = client.post(
            "/collections/8/add-books",
            data={"book_ids": ["1"]},
            follow_redirects=False,
        )

        assert resp.status_code in (302, 303)
        mock_catalog.add_books_to_collection.assert_not_called()
