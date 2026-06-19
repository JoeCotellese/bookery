# ABOUTME: Unit tests for the kobo_reader module — opens KoboReader.sqlite read-only,
# ABOUTME: parses content rows, normalizes ContentID, and reads the device serial.

import logging
import sqlite3
from pathlib import Path

import pytest

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.device.kobo_reader import (
    KoboContentRow,
    _normalize_content_id,
    open_kobo_db,
    pull_read_state,
    read_content_rows,
    read_kobo_serial,
)
from bookery.metadata.types import BookMetadata


class TestNormalizeContentId:
    def test_strips_file_scheme(self) -> None:
        assert (
            _normalize_content_id("file:///mnt/onboard/Books/Foo.epub")
            == "/mnt/onboard/Books/Foo.epub"
        )

    def test_url_decodes_when_encoded(self) -> None:
        assert (
            _normalize_content_id("file:///mnt/onboard/Books/My%20Book.epub")
            == "/mnt/onboard/Books/My Book.epub"
        )

    def test_noop_when_unencoded(self) -> None:
        # Kobo Libra Colour firmware 4.45.23684 stores ContentID *un*encoded;
        # decoding must be a safe no-op when there's nothing to decode.
        assert (
            _normalize_content_id(
                "file:///mnt/onboard/Bookery/Asimov, Isaac/Foundation/Foundation.kepub.epub"
            )
            == "/mnt/onboard/Bookery/Asimov, Isaac/Foundation/Foundation.kepub.epub"
        )

    def test_leaves_non_file_scheme_unchanged(self) -> None:
        # Some Kobo rows reference non-file content (newsstand, store). Leave
        # untouched so callers can filter them out themselves.
        assert _normalize_content_id("http://kobobooks.com/foo") == "http://kobobooks.com/foo"


class TestReadKoboSerial:
    def test_parses_first_comma_separated_field(self, tmp_path: Path) -> None:
        kobo = tmp_path / ".kobo"
        kobo.mkdir()
        (kobo / "version").write_text("N428440071799,4.45.23684,...\n")
        assert read_kobo_serial(tmp_path) == "N428440071799"

    def test_falls_back_to_full_stripped_content_when_no_comma(self, tmp_path: Path) -> None:
        kobo = tmp_path / ".kobo"
        kobo.mkdir()
        (kobo / "version").write_text("OPAQUE-SERIAL\n")
        assert read_kobo_serial(tmp_path) == "OPAQUE-SERIAL"

    def test_raises_when_missing(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            read_kobo_serial(tmp_path)


def _create_kobo_db(path: Path) -> None:
    """Build a minimal KoboReader.sqlite with `content` rows that mirror real fields."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE content (
            ContentID            TEXT PRIMARY KEY,
            BookID               TEXT,
            ReadStatus           INTEGER,
            ___PercentRead       REAL,
            DateLastRead         TEXT,
            ChapterIDBookmarked  TEXT,
            MimeType             TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO content VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            # Top-level kepub — should appear.
            (
                "file:///mnt/onboard/Bookery/A/T/T.kepub.epub",
                None,
                2,
                1.0,
                "2026-05-20T10:00:00",
                None,
                "application/x-kobo-epub+zip",
            ),
            # Top-level raw EPUB — should appear (LIKE 'application/%epub%' catches both).
            (
                "file:///mnt/onboard/Bookery/A/T2/T2.epub",
                None,
                1,
                0.42,
                "2026-05-21T11:00:00",
                "OEBPS/ch3.xhtml",
                "application/epub+zip",
            ),
            # Chapter row (BookID is set) — should be excluded.
            (
                "/mnt/onboard/.../chapter.xhtml",
                "file:///mnt/onboard/Bookery/A/T/T.kepub.epub",
                0,
                None,
                None,
                None,
                "application/xhtml+xml",
            ),
            # Non-EPUB MimeType (e.g. PDF sideload) — excluded by WHERE clause.
            (
                "file:///mnt/onboard/Bookery/A/T3/T3.pdf",
                None,
                0,
                None,
                None,
                None,
                "application/pdf",
            ),
        ],
    )
    conn.commit()
    conn.close()


class TestOpenAndReadKoboDb:
    def test_opens_read_only_with_immutable_flag(self, tmp_path: Path) -> None:
        # The immutable=1 flag is what makes USB-mounted Kobo DBs work — verify
        # it's actually applied by asserting writes are rejected.
        db = tmp_path / "KoboReader.sqlite"
        _create_kobo_db(db)
        conn = open_kobo_db(db)
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO content (ContentID) VALUES ('x')")
        conn.close()

    def test_returns_only_top_level_epub_rows(self, tmp_path: Path) -> None:
        db = tmp_path / "KoboReader.sqlite"
        _create_kobo_db(db)
        conn = open_kobo_db(db)
        try:
            rows = read_content_rows(conn)
        finally:
            conn.close()
        content_ids = {r.content_id for r in rows}
        assert content_ids == {
            "file:///mnt/onboard/Bookery/A/T/T.kepub.epub",
            "file:///mnt/onboard/Bookery/A/T2/T2.epub",
        }

    def test_row_fields_round_trip(self, tmp_path: Path) -> None:
        db = tmp_path / "KoboReader.sqlite"
        _create_kobo_db(db)
        conn = open_kobo_db(db)
        try:
            rows = read_content_rows(conn)
        finally:
            conn.close()
        by_id = {r.content_id: r for r in rows}
        finished = by_id["file:///mnt/onboard/Bookery/A/T/T.kepub.epub"]
        reading = by_id["file:///mnt/onboard/Bookery/A/T2/T2.epub"]

        assert isinstance(finished, KoboContentRow)
        assert finished.read_status == 2
        assert finished.percent_read == 1.0
        assert finished.date_last_read == "2026-05-20T10:00:00"
        assert finished.chapter_id_bookmarked is None
        assert finished.mime_type == "application/x-kobo-epub+zip"

        assert reading.read_status == 1
        assert reading.percent_read == 0.42
        assert reading.chapter_id_bookmarked == "OEBPS/ch3.xhtml"
        assert reading.mime_type == "application/epub+zip"


def _add_book_with_remote_path(
    catalog: LibraryCatalog,
    *,
    title: str,
    author: str,
    device_id: int,
    remote_path: str,
    now: str,
) -> int:
    md = BookMetadata(
        title=title,
        authors=[author],
        source_path=Path(f"/tmp/{title}.epub"),
    )
    book_id = catalog.add_book(md, file_hash=f"hash-{title}")
    catalog.upsert_device_file(
        device_id=device_id, book_id=book_id, remote_path=remote_path, now=now
    )
    return book_id


class TestPullReadState:
    def _build_mount(self, tmp_path: Path) -> tuple[Path, Path]:
        mount = tmp_path / "kobo"
        kobo_dir = mount / ".kobo"
        kobo_dir.mkdir(parents=True)
        (kobo_dir / "version").write_text("N428440071799,4.45.23684\n")
        return mount, kobo_dir

    def test_pulls_resolved_rows_and_skips_unknown(self, tmp_path: Path) -> None:
        mount, kobo_dir = self._build_mount(tmp_path)
        _create_kobo_db(kobo_dir / "KoboReader.sqlite")

        conn = open_library(tmp_path / "library.db")
        catalog = LibraryCatalog(conn)
        device_id = catalog.upsert_device(
            kind="kobo", serial="N428440071799", label=None, now="2026-05-26T08:00:00"
        )
        # Resolve one of the two top-level EPUBs in the fixture; leave the other
        # to confirm it counts as "skipped" (not present in our catalog).
        book_id = _add_book_with_remote_path(
            catalog,
            title="T",
            author="A",
            device_id=device_id,
            remote_path="/mnt/onboard/Bookery/A/T/T.kepub.epub",
            now="2026-05-26T08:00:00",
        )

        pulled, skipped = pull_read_state(
            catalog,
            device_id=device_id,
            mount_path=mount,
            now="2026-05-26T08:00:00",
        )
        assert (pulled, skipped) == (1, 1)
        row = conn.execute(
            "SELECT * FROM device_read_state WHERE device_id = ? AND book_id = ?",
            (device_id, book_id),
        ).fetchone()
        assert row["read_status"] == 2
        assert row["percent_read"] == 1.0
        assert row["last_read_at"] == "2026-05-20T10:00:00"
        # book_status mirror is seeded on pull.
        bs = conn.execute(
            "SELECT status, updated_at FROM book_status WHERE book_id = ?",
            (book_id,),
        ).fetchone()
        assert bs["status"] == 2
        assert bs["updated_at"] == "2026-05-20T10:00:00"

    def test_pull_does_not_overwrite_when_catalog_is_newer(self, tmp_path: Path) -> None:
        """The P2 merge: catalog with a strictly newer timestamp wins, so the
        user's bookery mark finished/reading/unread intent is preserved across syncs.
        """
        mount, kobo_dir = self._build_mount(tmp_path)
        _create_kobo_db(kobo_dir / "KoboReader.sqlite")
        conn = open_library(tmp_path / "library.db")
        catalog = LibraryCatalog(conn)
        device_id = catalog.upsert_device(
            kind="kobo", serial="N1", label=None, now="2026-05-26T08:00:00"
        )
        book_id = _add_book_with_remote_path(
            catalog,
            title="T",
            author="A",
            device_id=device_id,
            remote_path="/mnt/onboard/Bookery/A/T/T.kepub.epub",
            now="2026-05-26T08:00:00",
        )
        # Fixture's DateLastRead is "2026-05-20T10:00:00". Stamp the catalog
        # with a strictly-later ISO timestamp via the user write path.
        pull_read_state(catalog, device_id=device_id, mount_path=mount, now="t1")
        catalog.set_book_status(book_id=book_id, status=0, updated_at="2026-05-21T10:00:00")

        pulled, skipped = pull_read_state(catalog, device_id=device_id, mount_path=mount, now="t2")
        assert (pulled, skipped) == (1, 1)
        bs = conn.execute(
            "SELECT status, updated_at FROM book_status WHERE book_id = ?",
            (book_id,),
        ).fetchone()
        assert bs["status"] == 0
        assert bs["updated_at"] == "2026-05-21T10:00:00"
        # device_read_state was re-upserted with new pulled_at.
        row = conn.execute(
            "SELECT pulled_at FROM device_read_state WHERE device_id = ? AND book_id = ?",
            (device_id, book_id),
        ).fetchone()
        assert row["pulled_at"] == "t2"

    def test_pull_overwrites_book_status_when_device_is_newer(self, tmp_path: Path) -> None:
        """The other side of the merge: device with a strictly newer timestamp
        clobbers the catalog. Closes the "user read on device after marking
        unread on desktop" hole from #178's sync model.
        """
        mount, kobo_dir = self._build_mount(tmp_path)
        _create_kobo_db(kobo_dir / "KoboReader.sqlite")
        conn = open_library(tmp_path / "library.db")
        catalog = LibraryCatalog(conn)
        device_id = catalog.upsert_device(
            kind="kobo", serial="N1", label=None, now="2026-05-26T08:00:00"
        )
        book_id = _add_book_with_remote_path(
            catalog,
            title="T",
            author="A",
            device_id=device_id,
            remote_path="/mnt/onboard/Bookery/A/T/T.kepub.epub",
            now="2026-05-26T08:00:00",
        )
        # User marked unread on a date before the device's DateLastRead.
        catalog.set_book_status(book_id=book_id, status=0, updated_at="2026-05-19T10:00:00")

        pulled, _ = pull_read_state(catalog, device_id=device_id, mount_path=mount, now="t")
        assert pulled == 1
        bs = conn.execute(
            "SELECT status, updated_at FROM book_status WHERE book_id = ?",
            (book_id,),
        ).fetchone()
        # Fixture row has ReadStatus=2 (finished) and DateLastRead="2026-05-20T10:00:00".
        assert bs["status"] == 2
        assert bs["updated_at"] == "2026-05-20T10:00:00"

    def test_returns_zero_when_kobo_db_missing(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        mount, _ = self._build_mount(tmp_path)
        # KoboReader.sqlite is intentionally absent.
        conn = open_library(tmp_path / "library.db")
        catalog = LibraryCatalog(conn)
        device_id = catalog.upsert_device(kind="kobo", serial="N1", label=None, now="t")
        with caplog.at_level(logging.WARNING, logger="bookery.device.kobo_reader"):
            pulled, skipped = pull_read_state(
                catalog, device_id=device_id, mount_path=mount, now="t"
            )
        assert (pulled, skipped) == (0, 0)
        assert any("KoboReader.sqlite not found" in rec.message for rec in caplog.records)
