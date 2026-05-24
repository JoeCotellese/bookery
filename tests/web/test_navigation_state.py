# ABOUTME: Plan-02 navigation/URL-state matrix — edit URL, search form, return_to, subhead.
# ABOUTME: Each test row maps to a row in plans/02-web-navigation-url-state.md.

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
