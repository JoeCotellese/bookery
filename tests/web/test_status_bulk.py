# ABOUTME: Tests for POST /books/bulk-status — multi-select bulk-mark (P3 / #183).
# ABOUTME: Verifies one-transaction bulk write + refreshed list partial.

from bookery.db.status import STATUS_FINISHED, STATUS_READING, STATUS_UNREAD, BookStatus

from .conftest import make_book


class TestBulkStatusRoute:
    def test_marks_multiple_books_finished(self, mock_catalog, client) -> None:
        # The route re-renders the list partial after the write, so seed
        # browse() with the updated rows.
        books = [make_book(i, title=f"Book {i}") for i in (1, 2, 3)]
        mock_catalog.browse.return_value = (books, 3)
        mock_catalog.get_book_statuses.return_value = {
            1: BookStatus(book_id=1, status=STATUS_FINISHED, updated_at="t"),
            2: BookStatus(book_id=2, status=STATUS_FINISHED, updated_at="t"),
            3: BookStatus(book_id=3, status=STATUS_FINISHED, updated_at="t"),
        }
        mock_catalog.set_book_statuses_bulk.return_value = [1, 2, 3]

        response = client.post(
            "/books/bulk-status",
            data={"ids": ["1", "2", "3"], "status": "finished"},
        )

        assert response.status_code == 200
        mock_catalog.set_book_statuses_bulk.assert_called_once()
        kwargs = mock_catalog.set_book_statuses_bulk.call_args.kwargs
        assert kwargs["book_ids"] == [1, 2, 3]
        assert kwargs["status"] == STATUS_FINISHED
        assert "T" in kwargs["updated_at"]

    def test_marks_reading(self, mock_catalog, client) -> None:
        mock_catalog.browse.return_value = ([], 0)
        client.post("/books/bulk-status", data={"ids": ["7"], "status": "reading"})
        assert mock_catalog.set_book_statuses_bulk.call_args.kwargs["status"] == STATUS_READING

    def test_marks_unread(self, mock_catalog, client) -> None:
        mock_catalog.browse.return_value = ([], 0)
        client.post("/books/bulk-status", data={"ids": ["7"], "status": "unread"})
        assert mock_catalog.set_book_statuses_bulk.call_args.kwargs["status"] == STATUS_UNREAD

    def test_empty_ids_returns_400(self, mock_catalog, client) -> None:
        response = client.post("/books/bulk-status", data={"status": "finished"})
        assert response.status_code == 400
        mock_catalog.set_book_statuses_bulk.assert_not_called()

    def test_unknown_status_returns_400(self, mock_catalog, client) -> None:
        response = client.post(
            "/books/bulk-status",
            data={"ids": ["1"], "status": "garbage"},
        )
        assert response.status_code == 400
        mock_catalog.set_book_statuses_bulk.assert_not_called()

    def test_non_integer_ids_returns_400(self, mock_catalog, client) -> None:
        # A malformed form post shouldn't reach the catalog with garbage.
        response = client.post(
            "/books/bulk-status",
            data={"ids": ["1", "not-an-int"], "status": "finished"},
        )
        assert response.status_code == 400
        mock_catalog.set_book_statuses_bulk.assert_not_called()

    def test_returns_list_partial_no_full_page(self, mock_catalog, client) -> None:
        mock_catalog.browse.return_value = ([make_book(1)], 1)
        mock_catalog.set_book_statuses_bulk.return_value = [1]
        response = client.post(
            "/books/bulk-status",
            data={"ids": ["1"], "status": "finished"},
        )
        html = response.data.decode()
        # htmx swap target is #book-list — return only the partial markup.
        assert "<html" not in html
        assert "<head" not in html

    def test_preserves_filter_context_when_rerendering(self, mock_catalog, client) -> None:
        # If the user had ?status=reading in the URL when they hit bulk-mark,
        # the re-render should respect that filter so the now-finished rows
        # disappear from the visible page.
        mock_catalog.browse.return_value = ([], 0)
        mock_catalog.set_book_statuses_bulk.return_value = [1]
        client.post(
            "/books/bulk-status?status=reading",
            data={"ids": ["1"], "status": "finished"},
        )
        # browse was called twice — once for the bulk-mark re-render. Confirm
        # the filter was forwarded.
        last_call = mock_catalog.browse.call_args
        assert last_call.kwargs.get("status") == "reading"
