# ABOUTME: Tests for the Reading section on the book detail page.
# ABOUTME: Section renders when book_status or device_read_state exists; hidden otherwise.

from bookery.db.status import (
    STATUS_FINISHED,
    STATUS_READING,
    BookStatus,
    DeviceReadState,
)

from .conftest import make_book


class TestDetailReadingSection:
    def test_renders_when_book_status_present(self, mock_catalog, client) -> None:
        book = make_book(1, title="Sample")
        mock_catalog.get_by_id.return_value = book
        mock_catalog.get_book_status.return_value = BookStatus(
            book_id=1, status=STATUS_FINISHED, updated_at="2026-05-26T10:00:00+00:00"
        )
        mock_catalog.get_device_read_state_for_book.return_value = None

        response = client.get("/books/1")
        html = response.data.decode()

        # P3 (#183): the section always renders so the segmented status
        # control is reachable. The selected segment is signaled by
        # aria-pressed="true" + the active class.
        assert 'id="detail-reading"' in html
        assert "Finished" in html
        # Active state is on the Finished button.
        assert 'aria-pressed="true"' in html

    def test_renders_device_progress_and_last_opened(self, mock_catalog, client) -> None:
        book = make_book(1, title="Sample")
        mock_catalog.get_by_id.return_value = book
        mock_catalog.get_book_status.return_value = BookStatus(
            book_id=1, status=STATUS_READING, updated_at="t"
        )
        mock_catalog.get_device_read_state_for_book.return_value = DeviceReadState(
            device_id=1,
            device_kind="kobo",
            device_label="Mr. C's Libra",
            book_id=1,
            read_status=STATUS_READING,
            percent_read=0.47,
            last_read_at="2026-05-21T14:02:00+00:00",
            status_updated_at="2026-05-21T14:02:00+00:00",
        )

        response = client.get("/books/1")
        html = response.data.decode()

        assert "47%" in html
        assert "2026-05-21T14:02:00+00:00" in html
        assert "Kobo" in html
        assert "Mr. C&#39;s Libra" in html or "Mr. C's Libra" in html

    def test_section_renders_for_never_touched_book(self, mock_catalog, client) -> None:
        # P3 (#183) intentional contract shift: the section is always
        # present so the segmented control can record the user's first
        # toggle on an otherwise-untouched book. With no book_status row
        # all three segments are inactive (Unread defaults visually but
        # has aria-pressed="true" only because status defaults to 0).
        book = make_book(1, title="Untouched")
        mock_catalog.get_by_id.return_value = book
        mock_catalog.get_book_status.return_value = None
        mock_catalog.get_device_read_state_for_book.return_value = None

        response = client.get("/books/1")
        html = response.data.decode()

        assert "Untouched" in html
        assert 'id="detail-reading"' in html
        # All three segment buttons render.
        assert html.count("status-segment") >= 3

    def test_renders_device_only_when_no_book_status(self, mock_catalog, client) -> None:
        book = make_book(1, title="Just pulled")
        mock_catalog.get_by_id.return_value = book
        mock_catalog.get_book_status.return_value = None
        mock_catalog.get_device_read_state_for_book.return_value = DeviceReadState(
            device_id=1,
            device_kind="kobo",
            device_label=None,
            book_id=1,
            read_status=STATUS_READING,
            percent_read=0.10,
            last_read_at=None,
            status_updated_at="t",
        )

        response = client.get("/books/1")
        html = response.data.decode()

        assert 'id="detail-reading"' in html
        # Kind alone (no label) renders without parens.
        assert "Kobo" in html
        assert "(" not in html.split('id="detail-reading"')[1].split("</section>")[0]

    def test_device_label_omitted_when_missing(self, mock_catalog, client) -> None:
        book = make_book(1, title="No label")
        mock_catalog.get_by_id.return_value = book
        mock_catalog.get_book_status.return_value = BookStatus(
            book_id=1, status=STATUS_READING, updated_at="t"
        )
        mock_catalog.get_device_read_state_for_book.return_value = DeviceReadState(
            device_id=1,
            device_kind="kobo",
            device_label=None,
            book_id=1,
            read_status=STATUS_READING,
            percent_read=None,
            last_read_at=None,
            status_updated_at="t",
        )

        response = client.get("/books/1")
        html = response.data.decode()

        assert "Kobo" in html


class TestDetailReadingSegmentedControl:
    """P3 (#183) segmented status control assertions."""

    def test_renders_three_buttons(self, mock_catalog, client) -> None:
        mock_catalog.get_by_id.return_value = make_book(1, title="Rose")
        mock_catalog.get_book_status.return_value = None
        response = client.get("/books/1")
        html = response.data.decode()
        # Three segment buttons, each labeled.
        for label in ("Unread", "Reading", "Finished"):
            assert label in html
        # Buttons are explicit <button> elements so keyboard activation works.
        # Three buttons inside the segmented control.
        assert html.count('class="status-segment') >= 3

    def test_active_segment_is_current_status(self, mock_catalog, client) -> None:
        mock_catalog.get_by_id.return_value = make_book(1, title="Rose")
        mock_catalog.get_book_status.return_value = BookStatus(
            book_id=1, status=STATUS_READING, updated_at="t"
        )
        response = client.get("/books/1")
        html = response.data.decode()
        # Exactly one segment is pressed; the active class lands on the
        # matching one.
        assert html.count('aria-pressed="true"') == 1
        assert "status-segment-active" in html

    def test_buttons_post_to_toggle_route(self, mock_catalog, client) -> None:
        mock_catalog.get_by_id.return_value = make_book(1, title="Rose")
        mock_catalog.get_book_status.return_value = None
        response = client.get("/books/1")
        html = response.data.decode()
        assert 'hx-post="/books/1/status"' in html
        # Outer-swap on the section so the bulb-targeted update slots in.
        assert 'hx-target="#detail-reading"' in html
        assert 'hx-swap="outerHTML"' in html
        # All three labels are wired through hx-vals.
        for label in ("unread", "reading", "finished"):
            assert f'"status": "{label}"' in html

    def test_queued_indicator_renders_when_catalog_reports_it(self, mock_catalog, client) -> None:
        mock_catalog.get_by_id.return_value = make_book(1, title="Rose")
        mock_catalog.get_book_status.return_value = BookStatus(
            book_id=1, status=STATUS_READING, updated_at="t"
        )
        mock_catalog.is_status_queued_for_push.return_value = True
        response = client.get("/books/1")
        html = response.data.decode()
        assert "Queued for next sync" in html

    def test_queued_indicator_absent_when_catalog_reports_synced(
        self, mock_catalog, client
    ) -> None:
        mock_catalog.get_by_id.return_value = make_book(1, title="Rose")
        mock_catalog.get_book_status.return_value = BookStatus(
            book_id=1, status=STATUS_READING, updated_at="t"
        )
        mock_catalog.is_status_queued_for_push.return_value = False
        response = client.get("/books/1")
        html = response.data.decode()
        assert "Queued for next sync" not in html
