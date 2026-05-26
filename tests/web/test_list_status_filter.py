# ABOUTME: Tests for the /books status filter chip row + chip rendering (P3 / #183).
# ABOUTME: Verifies URL-driven state, AND-composition, and that chips share the URL-state pattern.

from .conftest import make_book


def _stub_browse(mock_catalog, *, books, total):
    mock_catalog.browse.return_value = (books, total)


class TestStatusFilterChipRow:
    """The four-chip filter row above the list (All / Unread / Reading / Finished)."""

    def test_chip_row_rendered_on_unfiltered_list(self, mock_catalog, client) -> None:
        _stub_browse(mock_catalog, books=[make_book(1)], total=1)
        response = client.get("/books")
        html = response.data.decode()
        # Chip row container is rendered even when no status filter is active —
        # it's the entry point for filtering.
        assert "status-filter" in html
        for label in ("All", "Unread", "Reading", "Finished"):
            assert label in html

    def test_active_chip_marked_with_aria_current(self, mock_catalog, client) -> None:
        _stub_browse(mock_catalog, books=[], total=0)
        response = client.get("/books?status=reading")
        html = response.data.decode()
        assert 'aria-current="page"' in html

    def test_all_chip_points_at_no_status_filter(self, mock_catalog, client) -> None:
        _stub_browse(mock_catalog, books=[], total=0)
        response = client.get("/books?status=finished")
        html = response.data.decode()
        # The "All" chip URL drops the status parameter.
        # Look for an anchor whose href has no `status=` segment but goes to /books.
        import re

        all_links = re.findall(
            r'<a [^>]*class="[^"]*status-filter-chip[^"]*"[^>]*href="([^"]*)"[^>]*>\s*All\s*</a>',
            html,
        )
        assert all_links, "All chip anchor not found"
        for href in all_links:
            assert "status=" not in href


class TestStatusFilterRouting:
    def test_route_forwards_status_to_catalog_browse(self, mock_catalog, client) -> None:
        _stub_browse(mock_catalog, books=[], total=0)
        client.get("/books?status=finished")
        kwargs = mock_catalog.browse.call_args.kwargs
        assert kwargs.get("status") == "finished"

    def test_status_combines_with_search_query(self, mock_catalog, client) -> None:
        _stub_browse(mock_catalog, books=[], total=0)
        client.get("/books?q=neuromancer&status=reading")
        kwargs = mock_catalog.browse.call_args.kwargs
        assert kwargs.get("q") == "neuromancer"
        assert kwargs.get("status") == "reading"

    def test_status_chip_rendered_in_active_filter_strip(
        self, mock_catalog, client
    ) -> None:
        # Existing _filter_chips strip displays a dismissible pill for each
        # active filter — the status filter must render with a friendly label.
        _stub_browse(mock_catalog, books=[make_book(1)], total=1)
        response = client.get("/books?status=reading")
        html = response.data.decode()
        # Active-filter pill carries the "Status: Reading" label.
        assert "filter-chip" in html
        assert "Status:" in html
        assert "Reading" in html


class TestBulkActionForm:
    """The list page renders the bulk-action form once with checkbox-driven inputs."""

    def test_form_present_with_three_actions(self, mock_catalog, client) -> None:
        _stub_browse(mock_catalog, books=[make_book(1), make_book(2)], total=2)
        response = client.get("/books")
        html = response.data.decode()
        assert 'id="bulk-status-form"' in html
        # The form's hx-post URL carries the current filter/sort context so
        # the re-render after a bulk write preserves it. Match the prefix
        # rather than the bare path.
        assert 'hx-post="/books/bulk-status' in html
        for label in ("Mark Reading", "Mark Finished", "Mark Unread"):
            assert label in html

    def test_checkbox_per_row_uses_form_attr(self, mock_catalog, client) -> None:
        _stub_browse(mock_catalog, books=[make_book(1), make_book(2)], total=2)
        response = client.get("/books")
        html = response.data.decode()
        # Each row's checkbox is bound to the out-of-table form via the
        # ``form="bulk-status-form"`` attribute so the markup can stay flat.
        assert html.count('form="bulk-status-form"') >= 2
        assert 'name="ids"' in html

    def test_checkbox_has_value_equal_to_book_id(self, mock_catalog, client) -> None:
        _stub_browse(mock_catalog, books=[make_book(42)], total=1)
        response = client.get("/books")
        html = response.data.decode()
        assert 'value="42"' in html

    def test_form_not_rendered_when_list_empty(self, mock_catalog, client) -> None:
        # Empty library → no checkboxes, no action bar.
        _stub_browse(mock_catalog, books=[], total=0)
        response = client.get("/books")
        html = response.data.decode()
        assert 'id="bulk-status-form"' not in html
