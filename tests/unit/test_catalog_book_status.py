# ABOUTME: Unit tests for LibraryCatalog read-status methods added in P1b.
# ABOUTME: Covers set/get/list APIs plus the device-state JOIN that powers info/detail.

from pathlib import Path

import pytest

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.db.status import (
    STATUS_FINISHED,
    STATUS_READING,
    STATUS_UNREAD,
    BookStatus,
    DeviceReadState,
)
from bookery.metadata.types import BookMetadata


@pytest.fixture()
def catalog(tmp_path: Path) -> LibraryCatalog:
    """Provide a LibraryCatalog backed by a temporary database."""
    conn = open_library(tmp_path / "test.db")
    return LibraryCatalog(conn)


def _add_book(catalog: LibraryCatalog, title: str, file_hash: str) -> int:
    """Add a minimally-populated book and return its ID."""
    return catalog.add_book(
        BookMetadata(
            title=title,
            authors=["Test Author"],
            author_sort="Author, Test",
            source_path=Path(f"/books/{file_hash}.epub"),
        ),
        file_hash=file_hash,
    )


class TestSetBookStatus:
    def test_inserts_new_row(self, catalog: LibraryCatalog) -> None:
        book_id = _add_book(catalog, "Rose", "h1")
        catalog.set_book_status(
            book_id=book_id, status=STATUS_READING, updated_at="2026-05-26T10:00:00+00:00"
        )
        status = catalog.get_book_status(book_id)
        assert status == BookStatus(
            book_id=book_id, status=STATUS_READING, updated_at="2026-05-26T10:00:00+00:00"
        )

    def test_overwrites_existing_row(self, catalog: LibraryCatalog) -> None:
        # Differs from seed_book_status_if_absent — the user path must overwrite.
        book_id = _add_book(catalog, "Rose", "h1")
        catalog.set_book_status(
            book_id=book_id, status=STATUS_READING, updated_at="2026-05-26T10:00:00+00:00"
        )
        catalog.set_book_status(
            book_id=book_id, status=STATUS_FINISHED, updated_at="2026-05-26T11:00:00+00:00"
        )
        status = catalog.get_book_status(book_id)
        assert status is not None
        assert status.status == STATUS_FINISHED
        assert status.updated_at == "2026-05-26T11:00:00+00:00"

    def test_idempotent_when_called_twice_same_values(self, catalog: LibraryCatalog) -> None:
        book_id = _add_book(catalog, "Rose", "h1")
        catalog.set_book_status(
            book_id=book_id, status=STATUS_FINISHED, updated_at="2026-05-26T10:00:00+00:00"
        )
        catalog.set_book_status(
            book_id=book_id, status=STATUS_FINISHED, updated_at="2026-05-26T10:00:00+00:00"
        )
        status = catalog.get_book_status(book_id)
        assert status is not None
        assert status.status == STATUS_FINISHED

    def test_raises_on_unknown_book(self, catalog: LibraryCatalog) -> None:
        with pytest.raises(ValueError, match="999"):
            catalog.set_book_status(
                book_id=999, status=STATUS_READING, updated_at="2026-05-26T10:00:00+00:00"
            )


class TestGetBookStatus:
    def test_returns_none_when_no_row(self, catalog: LibraryCatalog) -> None:
        book_id = _add_book(catalog, "Rose", "h1")
        assert catalog.get_book_status(book_id) is None

    def test_returns_none_for_unknown_book(self, catalog: LibraryCatalog) -> None:
        # No row in books table — get_book_status just queries book_status so
        # the result is the same as a known-book-with-no-status: None.
        assert catalog.get_book_status(999) is None


class TestGetBookStatuses:
    def test_returns_empty_for_empty_input(self, catalog: LibraryCatalog) -> None:
        assert catalog.get_book_statuses([]) == {}

    def test_returns_only_books_with_status_rows(self, catalog: LibraryCatalog) -> None:
        a = _add_book(catalog, "A", "ha")
        b = _add_book(catalog, "B", "hb")
        c = _add_book(catalog, "C", "hc")
        catalog.set_book_status(book_id=a, status=STATUS_READING, updated_at="t1")
        catalog.set_book_status(book_id=c, status=STATUS_FINISHED, updated_at="t2")

        result = catalog.get_book_statuses([a, b, c])

        assert set(result.keys()) == {a, c}
        assert result[a].status == STATUS_READING
        assert result[c].status == STATUS_FINISHED

    def test_unknown_ids_silently_skipped(self, catalog: LibraryCatalog) -> None:
        a = _add_book(catalog, "A", "ha")
        catalog.set_book_status(book_id=a, status=STATUS_READING, updated_at="t1")
        result = catalog.get_book_statuses([a, 999])
        assert set(result.keys()) == {a}


class TestListBooksByStatus:
    def test_returns_books_matching_status(self, catalog: LibraryCatalog) -> None:
        a = _add_book(catalog, "A finished", "ha")
        b = _add_book(catalog, "B reading", "hb")
        c = _add_book(catalog, "C finished", "hc")
        catalog.set_book_status(book_id=a, status=STATUS_FINISHED, updated_at="t1")
        catalog.set_book_status(book_id=b, status=STATUS_READING, updated_at="t2")
        catalog.set_book_status(book_id=c, status=STATUS_FINISHED, updated_at="t3")

        finished = catalog.list_books_by_status(STATUS_FINISHED)
        finished_ids = {r.id for r in finished}
        assert finished_ids == {a, c}

        reading = catalog.list_books_by_status(STATUS_READING)
        assert {r.id for r in reading} == {b}

    def test_ordered_by_title(self, catalog: LibraryCatalog) -> None:
        b = _add_book(catalog, "Beta", "hb")
        a = _add_book(catalog, "Alpha", "ha")
        catalog.set_book_status(book_id=a, status=STATUS_FINISHED, updated_at="t1")
        catalog.set_book_status(book_id=b, status=STATUS_FINISHED, updated_at="t2")
        result = catalog.list_books_by_status(STATUS_FINISHED)
        assert [r.metadata.title for r in result] == ["Alpha", "Beta"]

    def test_status_with_no_matches_returns_empty(self, catalog: LibraryCatalog) -> None:
        _add_book(catalog, "A", "ha")
        assert catalog.list_books_by_status(STATUS_FINISHED) == []


class TestListBooksUnread:
    def test_returns_books_with_no_status_row(self, catalog: LibraryCatalog) -> None:
        a = _add_book(catalog, "A no-row", "ha")
        b = _add_book(catalog, "B reading", "hb")
        catalog.set_book_status(book_id=b, status=STATUS_READING, updated_at="t")
        result = catalog.list_books_unread()
        assert {r.id for r in result} == {a}

    def test_includes_books_with_status_zero(self, catalog: LibraryCatalog) -> None:
        a = _add_book(catalog, "A no-row", "ha")
        b = _add_book(catalog, "B explicit-unread", "hb")
        c = _add_book(catalog, "C reading", "hc")
        catalog.set_book_status(book_id=b, status=STATUS_UNREAD, updated_at="t")
        catalog.set_book_status(book_id=c, status=STATUS_READING, updated_at="t")
        result = catalog.list_books_unread()
        assert {r.id for r in result} == {a, b}

    def test_ordered_by_title(self, catalog: LibraryCatalog) -> None:
        _add_book(catalog, "Zulu", "hz")
        _add_book(catalog, "Alpha", "ha")
        result = catalog.list_books_unread()
        assert [r.metadata.title for r in result] == ["Alpha", "Zulu"]


class TestGetDeviceReadStateForBook:
    def test_returns_none_when_no_device_row(self, catalog: LibraryCatalog) -> None:
        book_id = _add_book(catalog, "Rose", "h1")
        assert catalog.get_device_read_state_for_book(book_id) is None

    def test_joins_device_label_and_kind(self, catalog: LibraryCatalog) -> None:
        book_id = _add_book(catalog, "Rose", "h1")
        device_id = catalog.upsert_device(
            kind="kobo", serial="N428440071799", label="Mr. C's Libra", now="t0"
        )
        catalog.upsert_device_read_state(
            device_id=device_id,
            book_id=book_id,
            read_status=STATUS_READING,
            percent_read=0.47,
            last_read_at="2026-05-21T14:02:00+00:00",
            last_chapter_id=None,
            status_updated_at="2026-05-21T14:02:00+00:00",
            pulled_at="2026-05-26T10:00:00+00:00",
        )

        state = catalog.get_device_read_state_for_book(book_id)

        assert state is not None
        assert isinstance(state, DeviceReadState)
        assert state.device_kind == "kobo"
        assert state.device_label == "Mr. C's Libra"
        assert state.read_status == STATUS_READING
        assert state.percent_read == 0.47
        assert state.last_read_at == "2026-05-21T14:02:00+00:00"

    def test_returns_most_recent_when_multiple_devices(self, catalog: LibraryCatalog) -> None:
        # If two devices each have a row for the same book, return the most
        # recently updated one — that's what the user is actively reading.
        book_id = _add_book(catalog, "Rose", "h1")
        old = catalog.upsert_device(kind="kobo", serial="OLD", label="Old", now="t0")
        new = catalog.upsert_device(kind="kobo", serial="NEW", label="New", now="t0")
        catalog.upsert_device_read_state(
            device_id=old,
            book_id=book_id,
            read_status=STATUS_READING,
            percent_read=0.10,
            last_read_at="2026-05-01T00:00:00+00:00",
            last_chapter_id=None,
            status_updated_at="2026-05-01T00:00:00+00:00",
            pulled_at="2026-05-26T10:00:00+00:00",
        )
        catalog.upsert_device_read_state(
            device_id=new,
            book_id=book_id,
            read_status=STATUS_FINISHED,
            percent_read=1.0,
            last_read_at="2026-05-20T00:00:00+00:00",
            last_chapter_id=None,
            status_updated_at="2026-05-20T00:00:00+00:00",
            pulled_at="2026-05-26T10:00:00+00:00",
        )
        state = catalog.get_device_read_state_for_book(book_id)
        assert state is not None
        assert state.device_label == "New"
        assert state.read_status == STATUS_FINISHED
