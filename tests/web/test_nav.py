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


class TestMasthead:
    """Masthead carries the active-section indicator and live counts."""

    def _nav(self, html: str) -> str:
        match = re.search(r"<nav[^>]*site-nav.*?</nav>", html, re.DOTALL)
        assert match, "header must include the site-nav block"
        return match.group(0)

    def test_books_section_is_marked_active(self, client):
        nav = self._nav(client.get("/books").data.decode())
        link = re.search(r'<a[^>]*href="/books"[^>]*>', nav)
        assert link and 'aria-current="page"' in link.group(0)

    def test_collections_section_is_marked_active(self, mock_catalog, client):
        mock_catalog.list_collections.return_value = []
        nav = self._nav(client.get("/collections").data.decode())
        link = re.search(r'<a[^>]*href="/collections"[^>]*>', nav)
        assert link and 'aria-current="page"' in link.group(0)

    def test_nav_surfaces_live_counts(self, mock_catalog, client):
        mock_catalog.count_books.return_value = 640
        mock_catalog.count_collections.return_value = 3
        nav = self._nav(client.get("/books").data.decode())
        assert "640" in nav
        assert "3" in nav
