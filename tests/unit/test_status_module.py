# ABOUTME: Unit tests for db/status.py — read-status constants and dataclasses.
# ABOUTME: Pins the integer mapping shared by CLI, catalog, and web.

import dataclasses

import pytest

from bookery.db.status import (
    STATUS_FINISHED,
    STATUS_READING,
    STATUS_UNREAD,
    BookStatus,
    DeviceReadState,
    status_name,
)


class TestStatusConstants:
    def test_status_integers_match_kobo_mapping(self) -> None:
        # KoboContentRow.read_status uses 0=unread, 1=reading, 2=finished.
        # We mirror that mapping verbatim so the catalog write path never
        # has to remap integers between layers.
        assert STATUS_UNREAD == 0
        assert STATUS_READING == 1
        assert STATUS_FINISHED == 2


class TestStatusName:
    @pytest.mark.parametrize(
        "status,expected",
        [
            (STATUS_UNREAD, "Unread"),
            (STATUS_READING, "Reading"),
            (STATUS_FINISHED, "Finished"),
        ],
    )
    def test_known_statuses_have_human_names(self, status: int, expected: str) -> None:
        assert status_name(status) == expected

    def test_unknown_status_returns_neutral_label(self) -> None:
        # A future schema bump could add new values; rendering shouldn't crash.
        assert status_name(99) == "Unknown"


class TestBookStatus:
    def test_book_status_holds_fields(self) -> None:
        s = BookStatus(book_id=42, status=STATUS_READING, updated_at="2026-05-26T10:00:00+00:00")
        assert s.book_id == 42
        assert s.status == STATUS_READING
        assert s.updated_at == "2026-05-26T10:00:00+00:00"

    def test_book_status_is_frozen(self) -> None:
        s = BookStatus(book_id=1, status=STATUS_READING, updated_at="t")
        with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
            s.status = STATUS_FINISHED  # type: ignore[misc]


class TestDeviceReadState:
    def test_device_read_state_holds_all_fields(self) -> None:
        d = DeviceReadState(
            device_id=1,
            device_kind="kobo",
            device_label="Mr. C's Libra",
            book_id=42,
            read_status=STATUS_READING,
            percent_read=0.47,
            last_read_at="2026-05-21T14:02:00+00:00",
            status_updated_at="2026-05-21T14:02:00+00:00",
        )
        assert d.device_kind == "kobo"
        assert d.device_label == "Mr. C's Libra"
        assert d.percent_read == 0.47

    def test_device_read_state_label_optional(self) -> None:
        d = DeviceReadState(
            device_id=1,
            device_kind="kobo",
            device_label=None,
            book_id=42,
            read_status=STATUS_UNREAD,
            percent_read=None,
            last_read_at=None,
            status_updated_at="2026-05-26T10:00:00+00:00",
        )
        assert d.device_label is None
        assert d.percent_read is None
