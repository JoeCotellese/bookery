# ABOUTME: Tests for the primary site navigation in the web UI header.
# ABOUTME: Ensures Books and Collections are reachable from every page's header.

import re


class TestSiteNav:
    def test_books_page_has_collections_nav_link(self, client):
        html = client.get("/books").data.decode()
        nav = re.search(r"<nav[^>]*site-nav.*?</nav>", html, re.DOTALL)
        assert nav, "Header must include the site-nav block"
        assert 'href="/collections"' in nav.group(0)
        assert 'href="/books"' in nav.group(0)

    def test_collections_page_has_nav_link(self, mock_catalog, client):
        mock_catalog.list_collections.return_value = []
        html = client.get("/collections").data.decode()
        assert 'href="/collections"' in html
