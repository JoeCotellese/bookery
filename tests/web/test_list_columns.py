# ABOUTME: Integration tests for #198 configurable /books table columns.
# ABOUTME: Covers default set, cookie persistence, the toggle control, and tbody lock-step.

from .conftest import make_book


def _book_with_markers():
    """A book whose optional fields carry distinctive markers for tbody asserts."""
    return make_book(
        1,
        title="Dune",
        authors=["Frank Herbert"],
        isbn="ISBNMARKER123",
        language="LANGMARKER",
        publisher="PUBMARKER",
        metadata_matched_at="2026-01-02",
    )


class TestDefaultColumns:
    """First visit (no cookie) shows the lean default set."""

    def test_default_shows_added_and_enriched_not_reference_columns(self, mock_catalog, client):
        mock_catalog.browse.return_value = ([_book_with_markers()], 1)

        html = client.get("/books").data.decode()

        assert 'class="col-added"' in html
        assert 'class="col-enriched"' in html
        assert 'class="col-isbn"' not in html
        assert 'class="col-language"' not in html
        assert 'class="col-publisher"' not in html

    def test_hidden_columns_are_absent_from_tbody_too(self, mock_catalog, client):
        # Not display:none — the value markers must not be in the response at all.
        mock_catalog.browse.return_value = ([_book_with_markers()], 1)

        html = client.get("/books").data.decode()

        assert "ISBNMARKER123" not in html
        assert "PUBMARKER" not in html
        # Structural columns always render.
        assert "Dune" in html
        assert "Frank Herbert" in html


class TestCookieDrivenColumns:
    """A book_columns cookie overrides the default visible set."""

    def test_cookie_selects_visible_columns(self, mock_catalog, client):
        mock_catalog.browse.return_value = ([_book_with_markers()], 1)
        client.set_cookie("book_columns", "isbn,publisher")

        html = client.get("/books").data.decode()

        assert 'class="col-isbn"' in html
        assert 'class="col-publisher"' in html
        assert "ISBNMARKER123" in html
        assert "PUBMARKER" in html
        # Not in the cookie -> hidden.
        assert 'class="col-added"' not in html
        assert 'class="col-enriched"' not in html

    def test_empty_cookie_hides_all_toggleable_columns(self, mock_catalog, client):
        mock_catalog.browse.return_value = ([_book_with_markers()], 1)
        client.set_cookie("book_columns", "")

        html = client.get("/books").data.decode()

        for col in ("isbn", "language", "publisher", "added", "enriched"):
            assert f'class="col-{col}"' not in html
        # Structural columns survive.
        assert "Dune" in html


class TestColumnsControlPersistence:
    """Submitting the control writes the cookie and reflows the list."""

    def test_cols_set_writes_cookie_and_renders_selection(self, mock_catalog, client):
        mock_catalog.browse.return_value = ([_book_with_markers()], 1)

        resp = client.get("/books?cols_set=1&cols=isbn&cols=added")
        html = resp.data.decode()

        assert "Set-Cookie" in resp.headers
        assert "book_columns=" in resp.headers["Set-Cookie"]
        assert 'class="col-isbn"' in html
        assert 'class="col-added"' in html
        assert 'class="col-publisher"' not in html

    def test_cols_set_persists_to_a_later_request(self, mock_catalog, client):
        mock_catalog.browse.return_value = ([_book_with_markers()], 1)

        client.get("/books?cols_set=1&cols=publisher")
        # Same client carries the cookie forward; the bare /books reflects it.
        html = client.get("/books").data.decode()

        assert 'class="col-publisher"' in html
        assert 'class="col-added"' not in html

    def test_uncheck_all_persists_empty_selection(self, mock_catalog, client):
        mock_catalog.browse.return_value = ([_book_with_markers()], 1)

        client.get("/books?cols_set=1")  # no cols -> user cleared every box
        html = client.get("/books").data.decode()

        for col in ("isbn", "language", "publisher", "added", "enriched"):
            assert f'class="col-{col}"' not in html


class TestColumnsControlRendering:
    """The control reflects the active set with checked boxes."""

    def test_control_checkbox_state_mirrors_cookie(self, mock_catalog, client):
        mock_catalog.browse.return_value = ([_book_with_markers()], 1)
        client.set_cookie("book_columns", "isbn")

        html = client.get("/books").data.decode()

        # The control exposes a checkbox per toggleable column.
        assert 'name="cols" value="isbn"' in html
        assert 'name="cols" value="publisher"' in html
        # The cookie's column is checked; others are not.
        assert 'name="cols" value="isbn" checked' in html
        assert 'name="cols" value="added" checked' not in html


class TestBulkStatusRespectsColumns:
    """The bulk-mark re-render honors the cookie so columns don't snap back."""

    def test_bulk_partial_keeps_cookie_columns(self, mock_catalog, client):
        mock_catalog.browse.return_value = ([_book_with_markers()], 1)
        client.set_cookie("book_columns", "isbn")

        resp = client.post("/books/bulk-status", data={"ids": "1", "status": "reading"})
        html = resp.data.decode()

        assert 'class="col-isbn"' in html
        assert 'class="col-added"' not in html
