# ABOUTME: Tests for POST /books/<id>/status — single-book read-status toggle (P3 / #183).
# ABOUTME: Verifies write, partial render, validation, htmx contract.

from bookery.db.status import STATUS_FINISHED, STATUS_READING, STATUS_UNREAD, BookStatus

from .conftest import make_book


class TestStatusToggleRoute:
    def test_sets_status_reading(self, mock_catalog, client) -> None:
        mock_catalog.get_by_id.return_value = make_book(1, title="Rose")
        mock_catalog.get_book_status.return_value = BookStatus(
            book_id=1, status=STATUS_READING, updated_at="2026-05-26T10:00:00+00:00"
        )

        response = client.post("/books/1/status", data={"status": "reading"})

        assert response.status_code == 200
        mock_catalog.set_book_status.assert_called_once()
        kwargs = mock_catalog.set_book_status.call_args.kwargs
        assert kwargs["book_id"] == 1
        assert kwargs["status"] == STATUS_READING
        # updated_at must be a non-empty ISO-shaped timestamp — exact value
        # depends on wall-clock at test time, so just spot-check the shape.
        assert "T" in kwargs["updated_at"]

    def test_sets_status_finished(self, mock_catalog, client) -> None:
        mock_catalog.get_by_id.return_value = make_book(1, title="Rose")
        client.post("/books/1/status", data={"status": "finished"})
        assert mock_catalog.set_book_status.call_args.kwargs["status"] == STATUS_FINISHED

    def test_sets_status_unread(self, mock_catalog, client) -> None:
        mock_catalog.get_by_id.return_value = make_book(1, title="Rose")
        client.post("/books/1/status", data={"status": "unread"})
        assert mock_catalog.set_book_status.call_args.kwargs["status"] == STATUS_UNREAD

    def test_unknown_status_returns_400(self, mock_catalog, client) -> None:
        mock_catalog.get_by_id.return_value = make_book(1, title="Rose")
        response = client.post("/books/1/status", data={"status": "garbage"})
        assert response.status_code == 400
        mock_catalog.set_book_status.assert_not_called()

    def test_missing_status_returns_400(self, mock_catalog, client) -> None:
        mock_catalog.get_by_id.return_value = make_book(1, title="Rose")
        response = client.post("/books/1/status", data={})
        assert response.status_code == 400
        mock_catalog.set_book_status.assert_not_called()

    def test_unknown_book_returns_404(self, mock_catalog, client) -> None:
        mock_catalog.get_by_id.return_value = None
        response = client.post("/books/999/status", data={"status": "reading"})
        assert response.status_code == 404
        mock_catalog.set_book_status.assert_not_called()

    def test_returns_reading_partial_no_full_page(self, mock_catalog, client) -> None:
        mock_catalog.get_by_id.return_value = make_book(1, title="Rose")
        mock_catalog.get_book_status.return_value = BookStatus(
            book_id=1, status=STATUS_FINISHED, updated_at="2026-05-26T10:00:00+00:00"
        )
        response = client.post("/books/1/status", data={"status": "finished"})
        html = response.data.decode()
        # htmx outerHTML swap target — no full layout wrapping.
        assert "<html" not in html
        assert "<head" not in html
        # The partial renders the section by its anchor id so the swap lands.
        assert 'id="detail-reading"' in html
        # Updated status label appears in the partial.
        assert "Finished" in html

    def test_queued_indicator_present_when_queued(self, mock_catalog, client) -> None:
        mock_catalog.get_by_id.return_value = make_book(1, title="Rose")
        mock_catalog.get_book_status.return_value = BookStatus(
            book_id=1, status=STATUS_READING, updated_at="2026-05-26T10:00:00+00:00"
        )
        mock_catalog.is_status_queued_for_push.return_value = True
        response = client.post("/books/1/status", data={"status": "reading"})
        html = response.data.decode()
        assert "Queued for next sync" in html

    def test_queued_indicator_absent_when_synced(self, mock_catalog, client) -> None:
        mock_catalog.get_by_id.return_value = make_book(1, title="Rose")
        mock_catalog.get_book_status.return_value = BookStatus(
            book_id=1, status=STATUS_READING, updated_at="2026-05-26T10:00:00+00:00"
        )
        mock_catalog.is_status_queued_for_push.return_value = False
        response = client.post("/books/1/status", data={"status": "reading"})
        html = response.data.decode()
        assert "Queued for next sync" not in html
