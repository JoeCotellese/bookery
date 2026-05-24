# ABOUTME: Plan-02 navigation/URL-state matrix — edit URL, search form, return_to, subhead.
# ABOUTME: Each test row maps to a row in plans/02-web-navigation-url-state.md.

import re
from urllib.parse import parse_qs, urlsplit

from tests.web.conftest import make_book


def _extract_return_to(href: str) -> str | None:
    """Pull the ``return_to`` value out of an href, decoded."""
    qs = parse_qs(urlsplit(href).query)
    values = qs.get("return_to") or []
    return values[0] if values else None


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


class TestReturnToMechanism:
    """Step 3 / issue #122 — back navigation honors the originating list URL.

    The list page stamps each row anchor with ``?return_to=<list URL>``. Detail,
    edit, and enrich/diff routes thread the param through and use it as the
    back-link target, falling back to ``/books`` on deep-link entry. ``return_to``
    is sanitized to internal paths only — anything with a scheme or host is
    dropped to prevent open-redirect.
    """

    def test_list_row_anchors_carry_return_to(self, mock_catalog, client):
        """Each row's detail link encodes the current list URL as return_to."""
        mock_catalog.browse.return_value = ([make_book(1, title="A")], 1)
        html = client.get("/books?q=king").data.decode()
        # Find a row anchor and decode its return_to value back to the list URL.
        match = re.search(r'href="(/books/1\?[^"]*return_to=[^"]+)"', html)
        assert match, "expected a row anchor with return_to"
        decoded = _extract_return_to(match.group(1))
        assert decoded == "/books?q=king"

    def test_detail_back_link_honors_return_to(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)
        html = client.get("/books/1?return_to=%2Fbooks%3Fq%3Dking").data.decode()
        # The breadcrumb anchor targets the originating list URL, not /books.
        assert 'href="/books?q=king"' in html

    def test_detail_back_link_falls_back_to_books_on_deep_link(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)
        html = client.get("/books/1").data.decode()
        # No return_to → breadcrumb points at the unfiltered list.
        assert 'href="/books"' in html

    def test_detail_back_link_rejects_external_return_to(self, mock_catalog, client):
        """Open-redirect defense: scheme or host means we ignore return_to."""
        mock_catalog.get_by_id.return_value = make_book(1)
        for evil in ("https://evil.com", "//evil.com", "javascript:alert(1)"):
            html = client.get(f"/books/1?return_to={evil}").data.decode()
            assert "evil.com" not in html
            assert "javascript:" not in html

    def test_edit_button_carries_return_to(self, mock_catalog, client):
        """Clicking Edit on detail keeps the return_to chain intact."""
        mock_catalog.get_by_id.return_value = make_book(1)
        html = client.get("/books/1?return_to=%2Fbooks%3Fpage%3D3").data.decode()
        # Edit affordance points at /books/1/edit?return_to=…
        assert "/books/1/edit?return_to=" in html

    def test_edit_full_page_back_link_honors_return_to(self, mock_catalog, client):
        """Edit's breadcrumb back-to-book preserves the return_to chain.

        Two-step: from edit, "back to book" → detail with same return_to so
        from detail another "back" lands on the originating list.
        """
        mock_catalog.get_by_id.return_value = make_book(1)
        html = client.get("/books/1/edit?return_to=%2Fbooks%3Fpage%3D3").data.decode()
        # Back-to-book breadcrumb threads return_to so popping pages
        # eventually lands on the originating list URL.
        match = re.search(r'class="back-link"[^>]*>\s*<a href="([^"]+)"', html)
        assert match, "expected back-link anchor"
        href = match.group(1)
        assert href.startswith("/books/1")
        assert _extract_return_to(href) == "/books?page=3"

    def test_edit_save_pushes_url_with_return_to(self, mock_catalog, client):
        """After save, HX-Push-Url lands on detail with return_to preserved."""
        mock_catalog.get_by_id.return_value = make_book(1, title="Saved")
        response = client.post(
            "/books/1/edit?return_to=%2Fbooks%3Fq%3Dking",
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
        # HX-Push-Url should include return_to so the detail URL preserves the chain.
        push = response.headers.get("HX-Push-Url", "")
        assert push.startswith("/books/1")
        assert "return_to=" in push


class TestBookContextSubhead:
    """Step 4 / issue #127 — persistent book context subhead.

    Edit / enrich / diff sub-flows render a subhead with the book title and
    author and a link back to the detail view. The subhead survives htmx
    swaps because every fragment that replaces ``#book-content`` includes it
    at the top.
    """

    def _subhead_match(self, html: str):
        return re.search(
            r'<nav[^>]+class="book-subhead"[^>]*>(?P<body>.*?)</nav>',
            html,
            re.DOTALL,
        )

    def test_edit_form_renders_subhead(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1, title="Dune", authors=["Frank Herbert"])
        html = client.get("/books/1/edit", headers={"HX-Request": "true"}).data.decode()
        match = self._subhead_match(html)
        assert match, "expected book-subhead nav in edit fragment"
        body = match.group("body")
        assert "Dune" in body
        assert "Frank Herbert" in body
        assert 'href="/books/1' in body

    def test_edit_full_page_renders_subhead(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1, title="Dune", authors=["Frank Herbert"])
        html = client.get("/books/1/edit").data.decode()
        assert self._subhead_match(html), "expected book-subhead nav on full-page edit"

    def test_enrich_form_renders_subhead(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1, title="Dune", authors=["Frank Herbert"])
        html = client.get("/books/1/enrich").data.decode()
        match = self._subhead_match(html)
        assert match, "expected book-subhead nav in enrich form"
        body = match.group("body")
        assert "Dune" in body
        assert "Frank Herbert" in body

    def test_subhead_link_carries_return_to(self, mock_catalog, client):
        """The subhead's back-to-detail link threads return_to forward."""
        mock_catalog.get_by_id.return_value = make_book(1, title="Dune", authors=["Frank Herbert"])
        html = client.get("/books/1/edit?return_to=%2Fbooks%3Fq%3Ddune").data.decode()
        match = self._subhead_match(html)
        assert match
        href_match = re.search(r'href="([^"]+)"', match.group("body"))
        assert href_match
        href = href_match.group(1)
        assert href.startswith("/books/1")
        assert _extract_return_to(href) == "/books?q=dune"

    def test_detail_page_omits_subhead(self, mock_catalog, client):
        """Detail's own header already shows title + author — no subhead needed."""
        mock_catalog.get_by_id.return_value = make_book(1, title="Dune")
        html = client.get("/books/1").data.decode()
        assert not self._subhead_match(html)

    def test_detail_enrich_button_carries_return_to(self, mock_catalog, client):
        """Enrich affordance preserves the return_to chain into the sub-flow."""
        mock_catalog.get_by_id.return_value = make_book(1)
        html = client.get("/books/1?return_to=%2Fbooks%3Fpage%3D2").data.decode()
        assert "/books/1/enrich?return_to=" in html
