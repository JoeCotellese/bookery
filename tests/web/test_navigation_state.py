# ABOUTME: Plan-02 navigation/URL-state matrix — edit URL, search form, return_to, subhead.
# ABOUTME: Each test row maps to a row in plans/02-web-navigation-url-state.md.

import re

from tests.web.conftest import make_book


class TestEditUrlIsReal:
    """Step 1 / issue #131 — GET /books/<id>/edit is a real URL.

    Plain GET returns the full styled page so refresh, deep-link, and share
    all work. htmx GET returns the fragment for in-place swap. The detail
    page's Edit affordance pushes the URL so the browser sees the navigation.
    """

    def test_plain_get_returns_full_styled_page(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1, title="Book One")
        response = client.get("/books/1/edit")
        assert response.status_code == 200
        html = response.data.decode()
        # Base layout markers: doctype, site header, skip link.
        assert "<!DOCTYPE html>" in html
        assert "Skip to main content" in html
        assert 'class="logo"' in html
        # Edit form is still populated.
        assert 'name="title"' in html
        assert "Book One" in html

    def test_htmx_get_returns_fragment_only(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1, title="Book One")
        response = client.get("/books/1/edit", headers={"HX-Request": "true"})
        assert response.status_code == 200
        html = response.data.decode()
        # No base layout — fragment for in-place swap.
        assert "<!DOCTYPE html>" not in html
        assert "Skip to main content" not in html
        # Edit form still present.
        assert 'name="title"' in html
        assert "Book One" in html

    def test_refresh_on_edit_url_renders_full_page(self, mock_catalog, client):
        """Browser refresh sends no HX-Request header — same path as direct nav."""
        mock_catalog.get_by_id.return_value = make_book(1, title="Refreshed")
        response = client.get("/books/1/edit")
        html = response.data.decode()
        assert "<!DOCTYPE html>" in html
        assert "Refreshed" in html

    def test_edit_button_pushes_url(self, mock_catalog, client):
        """Detail's Edit affordance must push the edit URL so refresh/share work."""
        mock_catalog.get_by_id.return_value = make_book(1)
        html = client.get("/books/1").data.decode()
        # The Edit control resolves to a real link/button that updates the URL.
        # Accept either an anchor with href or an hx-push-url on the button.
        assert "/books/1/edit" in html
        assert "hx-push-url" in html or 'href="/books/1/edit"' in html

    def test_edit_missing_book_returns_404(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = None
        assert client.get("/books/999/edit").status_code == 404

    def test_save_pushes_url_back_to_detail(self, mock_catalog, client):
        """After save, htmx clients should land back on /books/<id>."""
        mock_catalog.get_by_id.return_value = make_book(1, title="Saved")
        response = client.post(
            "/books/1/edit",
            data={
                "title": "Saved",
                "authors": "Author",
                "isbn": "",
                "language": "",
                "publisher": "",
                "description": "",
                "series": "",
                "series_index": "",
            },
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        assert response.headers.get("HX-Push-Url") == "/books/1"


class TestSearchFormFallback:
    """Step 2 / issue #130 — search must work without JS.

    The search input lives inside a real ``<form action="/books" method="get">``
    so submitting via Enter or the visible button posts ``?q=…`` and the
    server returns filtered HTML. htmx keystroke search stays as progressive
    enhancement.
    """

    def _list_html(self, mock_catalog, client):
        mock_catalog.browse.return_value = ([], 0)
        return client.get("/books").data.decode()

    def test_search_input_wrapped_in_form(self, mock_catalog, client):
        html = self._list_html(mock_catalog, client)
        # A real form with action="/books" method="get" wraps the search input.
        form_match = re.search(
            r'<form[^>]*action="/books"[^>]*method="get"[^>]*>'
            r"(?P<body>.*?)</form>",
            html,
            re.DOTALL | re.IGNORECASE,
        )
        assert form_match, 'expected <form action="/books" method="get">'
        body = form_match.group("body")
        assert 'name="q"' in body, "search input must be inside the form"
        assert "<button" in body or 'type="submit"' in body, "form needs a submit affordance"

    def test_htmx_attrs_remain_for_progressive_enhancement(self, mock_catalog, client):
        html = self._list_html(mock_catalog, client)
        # Keystroke search still wired so JS clients get the live update.
        assert "hx-get" in html
        assert "hx-trigger" in html

    def test_non_htmx_get_with_query_returns_filtered_html(self, mock_catalog, client):
        """Pressing Enter / clicking submit hits /books?q=… as a plain GET.

        Already covered by the route, but pin it here so the regression
        surface is obvious: no HX-Request header, query string honored,
        full styled page returned.
        """
        mock_catalog.browse.return_value = ([make_book(1, title="The Shining")], 1)
        response = client.get("/books?q=king")
        assert response.status_code == 200
        html = response.data.decode()
        assert "<!DOCTYPE html>" in html
        assert "The Shining" in html
        # The catalog was queried with q="king".
        call = mock_catalog.browse.call_args
        assert call.kwargs.get("q") == "king"

    def test_search_input_value_is_preserved_after_submit(self, mock_catalog, client):
        """After a plain GET submit the input echoes the current query."""
        mock_catalog.browse.return_value = ([], 0)
        html = client.get("/books?q=tolkien").data.decode()
        assert 'value="tolkien"' in html
