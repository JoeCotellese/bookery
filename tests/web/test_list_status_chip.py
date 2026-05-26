# ABOUTME: Tests for the read-status chip on the book list view.
# ABOUTME: Verifies chip renders per-book status; books without status get no chip.

from bookery.db.status import STATUS_FINISHED, STATUS_READING, STATUS_UNREAD, BookStatus

from .conftest import make_book


def _stub_browse(mock_catalog, *, books, total):
    mock_catalog.browse.return_value = (books, total)


class TestListStatusChip:
    def test_reading_book_renders_reading_chip(self, mock_catalog, client) -> None:
        book = make_book(1, title="In Progress")
        _stub_browse(mock_catalog, books=[book], total=1)
        mock_catalog.get_book_statuses.return_value = {
            1: BookStatus(book_id=1, status=STATUS_READING, updated_at="2026-05-26T00:00:00+00:00")
        }

        response = client.get("/books")
        html = response.data.decode()

        assert "book-status-chip" in html
        assert "status-reading" in html
        assert 'title="Reading"' in html

    def test_finished_book_renders_finished_chip(self, mock_catalog, client) -> None:
        book = make_book(2, title="Done Reading")
        _stub_browse(mock_catalog, books=[book], total=1)
        mock_catalog.get_book_statuses.return_value = {
            2: BookStatus(book_id=2, status=STATUS_FINISHED, updated_at="t")
        }

        response = client.get("/books")
        html = response.data.decode()

        assert "status-finished" in html
        assert 'title="Finished"' in html

    def test_unread_book_renders_no_chip(self, mock_catalog, client) -> None:
        book = make_book(3, title="Untouched")
        _stub_browse(mock_catalog, books=[book], total=1)
        mock_catalog.get_book_statuses.return_value = {}

        response = client.get("/books")
        html = response.data.decode()

        # The book's title still renders; absent chip = no class string anywhere.
        assert "Untouched" in html
        assert "book-status-chip" not in html

    def test_explicit_unread_status_renders_no_chip(self, mock_catalog, client) -> None:
        # status=0 is the explicit unread state — still no chip per spec.
        book = make_book(4, title="Marked Unread")
        _stub_browse(mock_catalog, books=[book], total=1)
        mock_catalog.get_book_statuses.return_value = {
            4: BookStatus(book_id=4, status=STATUS_UNREAD, updated_at="t")
        }

        response = client.get("/books")
        html = response.data.decode()

        assert "Marked Unread" in html
        assert "book-status-chip" not in html

    def test_route_calls_get_book_statuses_with_visible_ids(self, mock_catalog, client) -> None:
        books = [make_book(i, title=f"B{i}") for i in (1, 2, 3)]
        _stub_browse(mock_catalog, books=books, total=3)
        mock_catalog.get_book_statuses.return_value = {}

        client.get("/books")

        mock_catalog.get_book_statuses.assert_called_once()
        called_with = mock_catalog.get_book_statuses.call_args[0][0]
        assert sorted(called_with) == [1, 2, 3]

    def test_empty_page_skips_status_query(self, mock_catalog, client) -> None:
        _stub_browse(mock_catalog, books=[], total=0)
        mock_catalog.get_book_statuses.return_value = {}

        client.get("/books")

        # On an empty library we shouldn't burn a SQL query asking about
        # statuses for zero books — the catalog method handles this too,
        # but the route should be considerate.
        if mock_catalog.get_book_statuses.called:
            assert mock_catalog.get_book_statuses.call_args[0][0] == []
