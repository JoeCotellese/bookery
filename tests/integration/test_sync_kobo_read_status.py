# ABOUTME: Integration test for the P1a Kobo read-status pull — runs a real sync
# ABOUTME: against a fixture KoboReader.sqlite and the real LibraryCatalog.

import sqlite3
from pathlib import Path

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.device.kepub_cache import KepubCache
from bookery.device.kobo import sync_library_to_kobo
from bookery.metadata.types import BookMetadata


class _StubKepubify:
    """Cheap kepubify replacement — writes a fake byte payload, no subprocess."""

    def __init__(self) -> None:
        self.version = "v4.4.0"

    def run(self, epub: Path, *, out_dir: Path) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        result = out_dir / f"{epub.stem}.kepub.epub"
        result.write_bytes(b"FAKE-KEPUB")
        return result

    def get_version(self) -> str:
        return self.version


def _build_fake_kobo_mount(root: Path) -> Path:
    mount = root / "kobo"
    kobo_dir = mount / ".kobo"
    kobo_dir.mkdir(parents=True)
    (kobo_dir / "version").write_text("N428440071799,4.45.23684\n")
    return mount


def _seed_kobo_db(path: Path, rows: list[tuple]) -> None:
    """Build a KoboReader.sqlite with the minimal `content` schema P1a queries.

    Each row is (ContentID, BookID, ReadStatus, ___PercentRead, DateLastRead,
    ChapterIDBookmarked, MimeType).
    """
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
    conn.executemany("INSERT INTO content VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def test_round_trip_sync_populates_read_state_and_book_status(tmp_path: Path) -> None:
    """End-to-end: a sync writes device_files, then a re-sync reads back state.

    Strategy B (record what we wrote) means the resolver isn't usable until the
    *first* sync writes device_files rows. So this test runs the sync twice:
    1. First sync: copies kepubs, writes device_files. read_states_skipped == N
       because the seeded KoboReader.sqlite predates the device_files rows.
    2. Re-seed KoboReader.sqlite so its ContentIDs now point at the paths
       written in step 1, then re-sync. Now resolver finds every row.
    """
    # --- Catalog with two real books in the library ---
    db_path = tmp_path / "library.db"
    conn = open_library(db_path)
    catalog = LibraryCatalog(conn)

    library = tmp_path / "library"
    epub_a = library / "Asimov" / "Foundation" / "Foundation.epub"
    epub_b = library / "Le Guin" / "Earthsea" / "Earthsea.epub"
    for path in (epub_a, epub_b):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"EPUB")

    book_a = catalog.add_book(
        BookMetadata(title="Foundation", authors=["Asimov"], source_path=epub_a),
        file_hash="hash-a",
        output_path=epub_a,
    )
    book_b = catalog.add_book(
        BookMetadata(title="Earthsea", authors=["Le Guin"], source_path=epub_b),
        file_hash="hash-b",
        output_path=epub_b,
    )

    # --- Mount + seeded device DB ---
    mount = _build_fake_kobo_mount(tmp_path)
    kobo_db = mount / ".kobo" / "KoboReader.sqlite"
    # First seed: the ContentIDs are what the device "expects" to find — we
    # know what paths the sync will create because they follow the
    # sanitize_component rules for "Asimov"/"Foundation" etc.
    expected_a = mount / "Books" / "Asimov" / "Foundation" / "Foundation.kepub.epub"
    expected_b = mount / "Books" / "Le Guin" / "Earthsea" / "Earthsea.kepub.epub"
    _seed_kobo_db(
        kobo_db,
        [
            (
                f"file://{expected_a}",
                None,
                2,
                1.0,
                "2026-05-20T10:00:00",
                None,
                "application/x-kobo-epub+zip",
            ),
            (
                f"file://{expected_b}",
                None,
                1,
                0.42,
                "2026-05-21T11:00:00",
                "OEBPS/ch3.xhtml",
                "application/x-kobo-epub+zip",
            ),
        ],
    )

    # --- Sync ---
    cache = KepubCache(tmp_path / "kepub.db")
    kepubify = _StubKepubify()

    # We need a list_all on the catalog — LibraryCatalog already has it.
    report = sync_library_to_kobo(
        catalog=catalog,
        target=mount,
        cache=cache,
        run_kepubify=kepubify.run,
        kepubify_version=kepubify.get_version,
        workspace_dir=tmp_path / "workspace",
        books_subdir="Books",
    )

    # --- Assertions ---
    assert set(report.copied) == {expected_a, expected_b}
    # On the FIRST sync the pull runs BEFORE the copy, so device_files is
    # still empty when the resolver looks up these ContentIDs — both rows
    # count as skipped. This is the documented behaviour (Strategy B).
    assert report.read_states_pulled == 0
    assert report.read_states_skipped == 2

    # device_files written for both books.
    rows = conn.execute(
        "SELECT book_id, remote_path FROM device_files ORDER BY book_id"
    ).fetchall()
    paths_by_book = {row["book_id"]: row["remote_path"] for row in rows}
    assert paths_by_book == {book_a: str(expected_a), book_b: str(expected_b)}

    # Devices row was upserted with the seeded serial.
    dev = conn.execute("SELECT kind, serial FROM devices").fetchone()
    assert dev["kind"] == "kobo"
    assert dev["serial"] == "N428440071799"

    # --- Second sync: now the resolver knows the paths. ---
    report2 = sync_library_to_kobo(
        catalog=catalog,
        target=mount,
        cache=cache,
        run_kepubify=kepubify.run,
        kepubify_version=kepubify.get_version,
        workspace_dir=tmp_path / "workspace",
        books_subdir="Books",
    )
    assert report2.read_states_pulled == 2
    assert report2.read_states_skipped == 0

    # device_read_state has both rows with the device-side values intact.
    states = {
        row["book_id"]: row
        for row in conn.execute(
            "SELECT book_id, read_status, percent_read, last_read_at, last_chapter_id "
            "FROM device_read_state"
        ).fetchall()
    }
    assert states[book_a]["read_status"] == 2
    assert states[book_a]["percent_read"] == 1.0
    assert states[book_a]["last_read_at"] == "2026-05-20T10:00:00"
    assert states[book_b]["read_status"] == 1
    assert states[book_b]["percent_read"] == 0.42
    assert states[book_b]["last_chapter_id"] == "OEBPS/ch3.xhtml"

    # book_status mirror seeded.
    statuses = {
        row["book_id"]: row["status"]
        for row in conn.execute("SELECT book_id, status FROM book_status").fetchall()
    }
    assert statuses == {book_a: 2, book_b: 1}

    conn.close()


def test_regression_sync_still_works_when_kobo_db_missing(tmp_path: Path) -> None:
    """Existing kepub-copy path must keep working when KoboReader.sqlite is absent."""
    db_path = tmp_path / "library.db"
    conn = open_library(db_path)
    catalog = LibraryCatalog(conn)

    library = tmp_path / "library"
    epub = library / "A" / "T" / "T.epub"
    epub.parent.mkdir(parents=True, exist_ok=True)
    epub.write_bytes(b"EPUB")
    book_id = catalog.add_book(
        BookMetadata(title="T", authors=["A"], source_path=epub),
        file_hash="hash-t",
        output_path=epub,
    )

    mount = _build_fake_kobo_mount(tmp_path)
    # NOTE: .kobo/version exists but KoboReader.sqlite does NOT.

    cache = KepubCache(tmp_path / "kepub.db")
    kepubify = _StubKepubify()
    report = sync_library_to_kobo(
        catalog=catalog,
        target=mount,
        cache=cache,
        run_kepubify=kepubify.run,
        kepubify_version=kepubify.get_version,
        workspace_dir=tmp_path / "workspace",
        books_subdir="Books",
    )

    expected = mount / "Books" / "A" / "T" / "T.kepub.epub"
    assert report.copied == [expected]
    assert report.read_states_pulled == 0
    assert report.read_states_skipped == 0
    # device_files still written so a future pull can resolve this book.
    row = conn.execute(
        "SELECT book_id FROM device_files WHERE remote_path = ?", (str(expected),)
    ).fetchone()
    assert row["book_id"] == book_id
    conn.close()
