# ABOUTME: Unit tests for the device/read-status catalog methods added in SCHEMA_V8.
# ABOUTME: Covers upsert_device, upsert_device_file, resolve_book_id_for_remote_path,
# ABOUTME: upsert_device_read_state, seed_book_status_if_absent.

from pathlib import Path

import pytest

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


@pytest.fixture()
def catalog(tmp_path: Path) -> LibraryCatalog:
    conn = open_library(tmp_path / "test.db")
    return LibraryCatalog(conn)


def _add_book(catalog: LibraryCatalog, title: str = "T", author: str = "A") -> int:
    md = BookMetadata(
        title=title,
        authors=[author],
        source_path=Path(f"/tmp/{title}-{author}.epub"),
    )
    return catalog.add_book(md, file_hash=f"hash-{title}-{author}")


class TestUpsertDevice:
    def test_insert_returns_new_id(self, catalog: LibraryCatalog) -> None:
        device_id = catalog.upsert_device(
            kind="kobo", serial="N1", label=None, now="2026-05-26T08:00:00"
        )
        assert isinstance(device_id, int)
        assert device_id > 0

    def test_second_insert_same_serial_returns_same_id(
        self, catalog: LibraryCatalog
    ) -> None:
        first = catalog.upsert_device(
            kind="kobo", serial="N1", label=None, now="2026-05-26T08:00:00"
        )
        second = catalog.upsert_device(
            kind="kobo", serial="N1", label="Bedside Kobo", now="2026-05-26T09:00:00"
        )
        assert first == second

    def test_second_insert_updates_last_seen_at_and_label(
        self, catalog: LibraryCatalog
    ) -> None:
        catalog.upsert_device(
            kind="kobo", serial="N1", label=None, now="2026-05-26T08:00:00"
        )
        catalog.upsert_device(
            kind="kobo", serial="N1", label="Bedside Kobo", now="2026-05-26T09:00:00"
        )
        row = catalog._conn.execute(
            "SELECT label, last_seen_at FROM devices WHERE kind = ? AND serial = ?",
            ("kobo", "N1"),
        ).fetchone()
        assert row["label"] == "Bedside Kobo"
        assert row["last_seen_at"] == "2026-05-26T09:00:00"

    def test_different_serial_gets_different_id(self, catalog: LibraryCatalog) -> None:
        first = catalog.upsert_device(
            kind="kobo", serial="N1", label=None, now="2026-05-26T08:00:00"
        )
        second = catalog.upsert_device(
            kind="kobo", serial="N2", label=None, now="2026-05-26T08:00:00"
        )
        assert first != second


class TestUpsertDeviceFile:
    def test_insert_then_resolve_round_trip(self, catalog: LibraryCatalog) -> None:
        device_id = catalog.upsert_device(
            kind="kobo", serial="N1", label=None, now="2026-05-26T08:00:00"
        )
        book_id = _add_book(catalog)
        path = "/Volumes/KOBOeReader/Bookery/A/T/T.kepub.epub"
        catalog.upsert_device_file(
            device_id=device_id,
            book_id=book_id,
            remote_path=path,
            now="2026-05-26T08:00:00",
        )
        assert (
            catalog.resolve_book_id_for_remote_path(
                device_id=device_id, remote_path=path
            )
            == book_id
        )

    def test_resolver_returns_none_when_missing(self, catalog: LibraryCatalog) -> None:
        device_id = catalog.upsert_device(
            kind="kobo", serial="N1", label=None, now="2026-05-26T08:00:00"
        )
        assert (
            catalog.resolve_book_id_for_remote_path(
                device_id=device_id, remote_path="/nowhere"
            )
            is None
        )

    def test_reinsert_is_idempotent_and_updates_written_at(
        self, catalog: LibraryCatalog
    ) -> None:
        device_id = catalog.upsert_device(
            kind="kobo", serial="N1", label=None, now="2026-05-26T08:00:00"
        )
        book_id = _add_book(catalog)
        path = "/Volumes/KOBOeReader/Bookery/A/T/T.kepub.epub"
        catalog.upsert_device_file(
            device_id=device_id,
            book_id=book_id,
            remote_path=path,
            now="2026-05-26T08:00:00",
        )
        catalog.upsert_device_file(
            device_id=device_id,
            book_id=book_id,
            remote_path=path,
            now="2026-05-26T09:00:00",
        )
        rows = catalog._conn.execute(
            "SELECT written_at FROM device_files WHERE device_id = ? AND book_id = ?",
            (device_id, book_id),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["written_at"] == "2026-05-26T09:00:00"

    def test_reinsert_with_new_path_updates_path(
        self, catalog: LibraryCatalog
    ) -> None:
        # If a book moves on the device (e.g. retitled in catalog), the new path
        # must overwrite the old — otherwise the resolver would silently miss the
        # current file.
        device_id = catalog.upsert_device(
            kind="kobo", serial="N1", label=None, now="2026-05-26T08:00:00"
        )
        book_id = _add_book(catalog)
        catalog.upsert_device_file(
            device_id=device_id,
            book_id=book_id,
            remote_path="/old/path.kepub.epub",
            now="2026-05-26T08:00:00",
        )
        catalog.upsert_device_file(
            device_id=device_id,
            book_id=book_id,
            remote_path="/new/path.kepub.epub",
            now="2026-05-26T09:00:00",
        )
        assert (
            catalog.resolve_book_id_for_remote_path(
                device_id=device_id, remote_path="/new/path.kepub.epub"
            )
            == book_id
        )
        assert (
            catalog.resolve_book_id_for_remote_path(
                device_id=device_id, remote_path="/old/path.kepub.epub"
            )
            is None
        )


class TestUpsertDeviceReadState:
    def test_insert_then_update_all_fields(self, catalog: LibraryCatalog) -> None:
        device_id = catalog.upsert_device(
            kind="kobo", serial="N1", label=None, now="2026-05-26T08:00:00"
        )
        book_id = _add_book(catalog)
        catalog.upsert_device_read_state(
            device_id=device_id,
            book_id=book_id,
            read_status=1,
            percent_read=0.25,
            last_read_at="2026-05-20T10:00:00",
            last_chapter_id="OEBPS/ch3.xhtml",
            status_updated_at="2026-05-20T10:00:00",
            pulled_at="2026-05-26T08:00:00",
        )
        catalog.upsert_device_read_state(
            device_id=device_id,
            book_id=book_id,
            read_status=2,
            percent_read=1.0,
            last_read_at="2026-05-25T22:00:00",
            last_chapter_id=None,
            status_updated_at="2026-05-25T22:00:00",
            pulled_at="2026-05-26T09:00:00",
        )
        row = catalog._conn.execute(
            "SELECT * FROM device_read_state WHERE device_id = ? AND book_id = ?",
            (device_id, book_id),
        ).fetchone()
        assert row["read_status"] == 2
        assert row["percent_read"] == 1.0
        assert row["last_read_at"] == "2026-05-25T22:00:00"
        assert row["last_chapter_id"] is None
        assert row["status_updated_at"] == "2026-05-25T22:00:00"
        assert row["pulled_at"] == "2026-05-26T09:00:00"


class TestSeedBookStatusIfAbsent:
    def test_first_call_inserts(self, catalog: LibraryCatalog) -> None:
        book_id = _add_book(catalog)
        catalog.seed_book_status_if_absent(
            book_id=book_id, status=1, updated_at="2026-05-26T08:00:00"
        )
        row = catalog._conn.execute(
            "SELECT status, updated_at FROM book_status WHERE book_id = ?",
            (book_id,),
        ).fetchone()
        assert row["status"] == 1
        assert row["updated_at"] == "2026-05-26T08:00:00"

    def test_second_call_does_not_overwrite(self, catalog: LibraryCatalog) -> None:
        # P1b: `bookery read` sets status via a different path. The pull must
        # never clobber a user's intentional status change — it only seeds when
        # the row is absent. ON CONFLICT (book_id) DO NOTHING.
        book_id = _add_book(catalog)
        catalog.seed_book_status_if_absent(
            book_id=book_id, status=2, updated_at="2026-05-26T08:00:00"
        )
        catalog.seed_book_status_if_absent(
            book_id=book_id, status=0, updated_at="2026-05-26T09:00:00"
        )
        row = catalog._conn.execute(
            "SELECT status, updated_at FROM book_status WHERE book_id = ?",
            (book_id,),
        ).fetchone()
        assert row["status"] == 2
        assert row["updated_at"] == "2026-05-26T08:00:00"
