# ABOUTME: Integration tests for the P2 read-status push — exercises the full
# ABOUTME: sync round-trip with catalog -> device writes, backups, and merge.

import sqlite3
from pathlib import Path

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.db.status import STATUS_FINISHED, STATUS_READING, STATUS_UNREAD
from bookery.device.kepub_cache import KepubCache
from bookery.device.kobo import sync_library_to_kobo
from bookery.metadata.types import BookMetadata


class _StubKepubify:
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
    """Build a KoboReader.sqlite with the columns the writer touches.

    Each row: (ContentID, ReadStatus, ___PercentRead, DateLastRead, MimeType).
    BookID column is included (NULL for top-level book rows) so the P1a
    read_content_rows filter still picks the row up.
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
    expanded = [(cid, None, rs, pr, dlr, None, mime) for cid, rs, pr, dlr, mime in rows]
    conn.executemany("INSERT INTO content VALUES (?, ?, ?, ?, ?, ?, ?)", expanded)
    conn.commit()
    conn.close()


def _add_library_book(library: Path, author: str, title: str) -> Path:
    epub = library / author / title / f"{title}.epub"
    epub.parent.mkdir(parents=True, exist_ok=True)
    epub.write_bytes(b"EPUB")
    return epub


def _add_catalog_book(catalog: LibraryCatalog, epub: Path, title: str, author: str) -> int:
    return catalog.add_book(
        BookMetadata(title=title, authors=[author], source_path=epub),
        file_hash=f"hash-{title}",
        output_path=epub,
    )


def _run_sync(
    *,
    catalog: LibraryCatalog,
    mount: Path,
    tmp_path: Path,
    backup_root: Path | None = None,
    status_push_enabled: bool = True,
):
    return sync_library_to_kobo(
        catalog=catalog,
        target=mount,
        cache=KepubCache(tmp_path / "kepub.db"),
        run_kepubify=_StubKepubify().run,
        kepubify_version=_StubKepubify().get_version,
        workspace_dir=tmp_path / "workspace",
        books_subdir="Books",
        backup_root=backup_root,
        status_push_enabled=status_push_enabled,
    )


def test_catalog_newer_pushes_finished_to_device(tmp_path: Path) -> None:
    """User marks a book finished in bookery, sync, device row reflects it."""
    db_path = tmp_path / "library.db"
    conn = open_library(db_path)
    catalog = LibraryCatalog(conn)

    library = tmp_path / "library"
    epub = _add_library_book(library, "Asimov", "Foundation")
    book_id = _add_catalog_book(catalog, epub, "Foundation", "Asimov")

    mount = _build_fake_kobo_mount(tmp_path)
    kobo_db = mount / ".kobo" / "KoboReader.sqlite"
    # Device has the book but only reports it as Unread.
    _seed_kobo_db(
        kobo_db,
        [
            (
                "file:///mnt/onboard/Books/Asimov/Foundation/Foundation.kepub.epub",
                0,
                0.0,
                "2026-05-20T10:00:00",
                "application/x-kobo-epub+zip",
            ),
        ],
    )
    # First sync just populates device_files (so the second sync can resolve
    # the ContentID + push). After it, mark the book finished with a strictly
    # later catalog timestamp than the device's DateLastRead.
    _run_sync(catalog=catalog, mount=mount, tmp_path=tmp_path / "sync1")
    catalog.set_book_status(
        book_id=book_id,
        status=STATUS_FINISHED,
        updated_at="2026-05-26T11:00:00",
    )

    backup_root = tmp_path / "backups"
    report = _run_sync(
        catalog=catalog,
        mount=mount,
        tmp_path=tmp_path / "sync2",
        backup_root=backup_root,
    )

    assert report.read_statuses_pushed == 1
    assert report.read_status_push_failed == []
    # Device row reflects the push.
    device_row = sqlite3.connect(str(kobo_db)).execute(
        "SELECT ReadStatus, ___PercentRead, DateLastRead FROM content WHERE ContentID = ?",
        ("file:///mnt/onboard/Books/Asimov/Foundation/Foundation.kepub.epub",),
    ).fetchone()
    assert device_row[0] == 2
    assert device_row[1] == 100.0
    # DateLastRead was stamped (just check it's no longer the seeded value).
    assert device_row[2] != "2026-05-20T10:00:00"
    # Backup was created.
    assert report.backup_path is not None
    assert report.backup_path.exists()


def test_idempotent_second_sync_pushes_nothing(tmp_path: Path) -> None:
    """After a push, the catalog and device timestamps match; the tiebreak
    sends the book device-side, so the next sync pushes nothing.
    """
    db_path = tmp_path / "library.db"
    conn = open_library(db_path)
    catalog = LibraryCatalog(conn)
    library = tmp_path / "library"
    epub = _add_library_book(library, "Asimov", "Foundation")
    _add_catalog_book(catalog, epub, "Foundation", "Asimov")

    mount = _build_fake_kobo_mount(tmp_path)
    kobo_db = mount / ".kobo" / "KoboReader.sqlite"
    _seed_kobo_db(
        kobo_db,
        [
            (
                "file:///mnt/onboard/Books/Asimov/Foundation/Foundation.kepub.epub",
                0,
                0.0,
                "2026-05-20T10:00:00",
                "application/x-kobo-epub+zip",
            ),
        ],
    )
    _run_sync(catalog=catalog, mount=mount, tmp_path=tmp_path / "sync1")
    catalog.set_book_status(
        book_id=1, status=STATUS_FINISHED, updated_at="2026-05-26T11:00:00"
    )
    first = _run_sync(
        catalog=catalog,
        mount=mount,
        tmp_path=tmp_path / "sync2",
        backup_root=tmp_path / "backups",
    )
    assert first.read_statuses_pushed == 1
    second = _run_sync(
        catalog=catalog,
        mount=mount,
        tmp_path=tmp_path / "sync3",
        backup_root=tmp_path / "backups",
    )
    assert second.read_statuses_pushed == 0


def test_device_newer_overwrites_catalog(tmp_path: Path) -> None:
    """Device reports a later read than the catalog's unread mark — the
    merge picks the device direction and bookery now shows finished."""
    db_path = tmp_path / "library.db"
    conn = open_library(db_path)
    catalog = LibraryCatalog(conn)
    library = tmp_path / "library"
    epub = _add_library_book(library, "Asimov", "Foundation")
    book_id = _add_catalog_book(catalog, epub, "Foundation", "Asimov")

    mount = _build_fake_kobo_mount(tmp_path)
    kobo_db = mount / ".kobo" / "KoboReader.sqlite"
    _seed_kobo_db(
        kobo_db,
        [
            (
                "file:///mnt/onboard/Books/Asimov/Foundation/Foundation.kepub.epub",
                2,
                100.0,
                "2026-05-25T10:00:00",
                "application/x-kobo-epub+zip",
            ),
        ],
    )
    _run_sync(catalog=catalog, mount=mount, tmp_path=tmp_path / "sync1")
    # User marked unread BEFORE the device's later finished-read.
    catalog.set_book_status(
        book_id=book_id, status=STATUS_UNREAD, updated_at="2026-05-19T10:00:00"
    )
    report = _run_sync(
        catalog=catalog,
        mount=mount,
        tmp_path=tmp_path / "sync2",
        backup_root=tmp_path / "backups",
    )
    bs = catalog.get_book_status(book_id)
    assert bs is not None
    assert bs.status == STATUS_FINISHED
    # Nothing to push back — device already has the correct state.
    assert report.read_statuses_pushed == 0


def test_no_status_push_skips_writer_and_backup(tmp_path: Path) -> None:
    db_path = tmp_path / "library.db"
    conn = open_library(db_path)
    catalog = LibraryCatalog(conn)
    library = tmp_path / "library"
    epub = _add_library_book(library, "Asimov", "Foundation")
    book_id = _add_catalog_book(catalog, epub, "Foundation", "Asimov")

    mount = _build_fake_kobo_mount(tmp_path)
    kobo_db = mount / ".kobo" / "KoboReader.sqlite"
    _seed_kobo_db(
        kobo_db,
        [
            (
                "file:///mnt/onboard/Books/Asimov/Foundation/Foundation.kepub.epub",
                0,
                0.0,
                "2026-05-20T10:00:00",
                "application/x-kobo-epub+zip",
            ),
        ],
    )
    _run_sync(catalog=catalog, mount=mount, tmp_path=tmp_path / "sync1")
    catalog.set_book_status(
        book_id=book_id, status=STATUS_FINISHED, updated_at="2026-05-26T11:00:00"
    )
    backup_root = tmp_path / "backups"
    report = _run_sync(
        catalog=catalog,
        mount=mount,
        tmp_path=tmp_path / "sync2",
        backup_root=backup_root,
        status_push_enabled=False,
    )
    assert report.read_statuses_pushed == 0
    assert report.backup_path is None
    # Device row is untouched — still Unread.
    device_row = sqlite3.connect(str(kobo_db)).execute(
        "SELECT ReadStatus FROM content WHERE ContentID = ?",
        ("file:///mnt/onboard/Books/Asimov/Foundation/Foundation.kepub.epub",),
    ).fetchone()
    assert device_row[0] == 0


def test_cached_path_backfills_device_files_for_pre_p1a_book(tmp_path: Path) -> None:
    """Regression for #188.

    Simulates a book that pre-dates P1a (#180): the kepub is already on the
    device, the kepubify cache row exists, but ``device_files`` has no row
    for it. Pre-P1a syncs never wrote one, and the cached short-circuit in
    ``_sync_record`` was skipping the upsert on every subsequent run — so
    the read-status push half of the sync couldn't see the book at all.

    With the fix, the cached path re-stamps ``device_files`` and a later
    status change in the catalog gets pushed to the device on the next sync.
    """
    db_path = tmp_path / "library.db"
    conn = open_library(db_path)
    catalog = LibraryCatalog(conn)
    library = tmp_path / "library"
    epub = _add_library_book(library, "Asimov", "Foundation")
    book_id = _add_catalog_book(catalog, epub, "Foundation", "Asimov")

    mount = _build_fake_kobo_mount(tmp_path)
    kobo_db = mount / ".kobo" / "KoboReader.sqlite"
    _seed_kobo_db(
        kobo_db,
        [
            (
                "file:///mnt/onboard/Books/Asimov/Foundation/Foundation.kepub.epub",
                0,
                0.0,
                "2026-05-20T10:00:00",
                "application/x-kobo-epub+zip",
            ),
        ],
    )

    # The repro requires the kepubify cache to persist across syncs so that
    # the second run hits the cached short-circuit in ``_sync_record``. The
    # shared ``_run_sync`` helper creates a fresh cache per call, so wire up
    # an explicit shared cache + workspace here.
    shared_cache = KepubCache(tmp_path / "kepub.db")
    stub = _StubKepubify()

    def _sync(workspace_root: Path, *, backup_root: Path | None = None):
        return sync_library_to_kobo(
            catalog=catalog,
            target=mount,
            cache=shared_cache,
            run_kepubify=stub.run,
            kepubify_version=stub.get_version,
            workspace_dir=workspace_root,
            books_subdir="Books",
            backup_root=backup_root,
        )

    # Sync once normally — populates the kepubify cache and writes a
    # device_files row via the copy path.
    _sync(tmp_path / "sync1-ws")

    # Simulate pre-P1a state: wipe device_files so the cached path on the
    # next sync is the only opportunity to recreate the row.
    catalog._conn.execute("DELETE FROM device_files")
    catalog._conn.commit()

    catalog.set_book_status(
        book_id=book_id, status=STATUS_FINISHED, updated_at="2026-05-26T11:00:00"
    )

    # Second sync hits the cached path (kepub already on device, cache row
    # present). Without the fix, no device_files row is written and the
    # push silently no-ops.
    report = _sync(tmp_path / "sync2-ws", backup_root=tmp_path / "backups")

    assert report.read_statuses_pushed == 1
    assert report.read_status_push_failed == []
    device_row = sqlite3.connect(str(kobo_db)).execute(
        "SELECT ReadStatus FROM content WHERE ContentID = ?",
        ("file:///mnt/onboard/Books/Asimov/Foundation/Foundation.kepub.epub",),
    ).fetchone()
    assert device_row[0] == 2


def test_reading_status_pushes_without_clobbering_percent(tmp_path: Path) -> None:
    """STATUS_READING preserves the device's progress percentage."""
    db_path = tmp_path / "library.db"
    conn = open_library(db_path)
    catalog = LibraryCatalog(conn)
    library = tmp_path / "library"
    epub = _add_library_book(library, "Le Guin", "Earthsea")
    book_id = _add_catalog_book(catalog, epub, "Earthsea", "Le Guin")

    mount = _build_fake_kobo_mount(tmp_path)
    kobo_db = mount / ".kobo" / "KoboReader.sqlite"
    _seed_kobo_db(
        kobo_db,
        [
            (
                "file:///mnt/onboard/Books/Le Guin/Earthsea/Earthsea.kepub.epub",
                0,
                42.0,
                "2026-05-20T10:00:00",
                "application/x-kobo-epub+zip",
            ),
        ],
    )
    _run_sync(catalog=catalog, mount=mount, tmp_path=tmp_path / "sync1")
    catalog.set_book_status(
        book_id=book_id, status=STATUS_READING, updated_at="2026-05-26T11:00:00"
    )
    _run_sync(
        catalog=catalog,
        mount=mount,
        tmp_path=tmp_path / "sync2",
        backup_root=tmp_path / "backups",
    )
    device_row = sqlite3.connect(str(kobo_db)).execute(
        "SELECT ReadStatus, ___PercentRead FROM content WHERE ContentID = ?",
        ("file:///mnt/onboard/Books/Le Guin/Earthsea/Earthsea.kepub.epub",),
    ).fetchone()
    assert device_row[0] == 1
    # Percent untouched because status=reading skips that column.
    assert device_row[1] == 42.0
