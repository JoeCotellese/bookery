# ABOUTME: Resilience tests for #182 push — the sync must keep working when
# ABOUTME: KoboReader.sqlite is read-only or the backup directory is corrupted.

import logging
import sqlite3
import stat
from pathlib import Path

import pytest

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.db.status import STATUS_FINISHED
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


def _build_mount(root: Path) -> Path:
    mount = root / "kobo"
    kobo_dir = mount / ".kobo"
    kobo_dir.mkdir(parents=True)
    (kobo_dir / "version").write_text("N428440071799,4.45.23684\n")
    return mount


def _seed_kobo_db(path: Path, content_id: str) -> None:
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
    conn.execute(
        "INSERT INTO content VALUES (?, NULL, 0, 0.0, '2026-05-20T10:00:00', NULL, ?)",
        (content_id, "application/x-kobo-epub+zip"),
    )
    conn.commit()
    conn.close()


def _seed_catalog(tmp_path: Path) -> tuple[LibraryCatalog, int, Path]:
    db_path = tmp_path / "library.db"
    conn = open_library(db_path)
    catalog = LibraryCatalog(conn)
    library = tmp_path / "library"
    epub = library / "Asimov" / "Foundation" / "Foundation.epub"
    epub.parent.mkdir(parents=True, exist_ok=True)
    epub.write_bytes(b"EPUB")
    book_id = catalog.add_book(
        BookMetadata(title="Foundation", authors=["Asimov"], source_path=epub),
        file_hash="hash-foundation",
        output_path=epub,
    )
    return catalog, book_id, library


def _run_sync(*, catalog: LibraryCatalog, mount: Path, tmp_path: Path, backup_root: Path):
    return sync_library_to_kobo(
        catalog=catalog,
        target=mount,
        cache=KepubCache(tmp_path / "kepub.db"),
        run_kepubify=_StubKepubify().run,
        kepubify_version=_StubKepubify().get_version,
        workspace_dir=tmp_path / "workspace",
        books_subdir="Books",
        backup_root=backup_root,
    )


def test_read_only_kobo_db_does_not_crash(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A read-only KoboReader.sqlite (mount quirk) must let the sync complete
    with the pull/copy phases intact and the push reported as a failure."""
    catalog, book_id, _ = _seed_catalog(tmp_path)
    mount = _build_mount(tmp_path)
    kobo_db = mount / ".kobo" / "KoboReader.sqlite"
    _seed_kobo_db(
        kobo_db,
        "file:///mnt/onboard/Books/Asimov/Foundation/Foundation.kepub.epub",
    )
    # First sync populates device_files normally.
    _run_sync(
        catalog=catalog,
        mount=mount,
        tmp_path=tmp_path / "s1",
        backup_root=tmp_path / "backups",
    )
    catalog.set_book_status(
        book_id=book_id, status=STATUS_FINISHED, updated_at="2026-05-26T11:00:00"
    )
    # Strip write permission from the device DB and its parent.
    kobo_db.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    parent_mode = (mount / ".kobo").stat().st_mode
    (mount / ".kobo").chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        with caplog.at_level(logging.WARNING, logger="bookery.device.kobo"):
            report = _run_sync(
                catalog=catalog,
                mount=mount,
                tmp_path=tmp_path / "s2",
                backup_root=tmp_path / "backups",
            )
    finally:
        # Restore so pytest can clean up the tmp dir.
        (mount / ".kobo").chmod(parent_mode)
        kobo_db.chmod(stat.S_IRUSR | stat.S_IWUSR)
    # Pull still completed (count of 1) because pulls open the DB read-only.
    assert report.read_states_pulled == 1
    # Push failed cleanly — failure list populated, push count zero.
    assert report.read_statuses_pushed == 0
    assert any("Read-status push failed" in rec.message for rec in caplog.records)


def test_corrupted_backup_dir_does_not_block_sync(tmp_path: Path) -> None:
    """If ~/.bookery/backups/<serial>/ exists as a regular file (not a dir),
    the backup attempt logs and returns None — the sync still pushes (we
    accept the unbacked-up push as a soft failure of the safety net, not a
    sync failure)."""
    catalog, book_id, _ = _seed_catalog(tmp_path)
    mount = _build_mount(tmp_path)
    kobo_db = mount / ".kobo" / "KoboReader.sqlite"
    _seed_kobo_db(
        kobo_db,
        "file:///mnt/onboard/Books/Asimov/Foundation/Foundation.kepub.epub",
    )
    _run_sync(
        catalog=catalog,
        mount=mount,
        tmp_path=tmp_path / "s1",
        backup_root=tmp_path / "backups",
    )
    catalog.set_book_status(
        book_id=book_id, status=STATUS_FINISHED, updated_at="2026-05-26T11:00:00"
    )

    backup_root = tmp_path / "backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    # Plant a regular file where the serial directory should live.
    (backup_root / "N428440071799").write_text("not a directory")

    report = _run_sync(
        catalog=catalog,
        mount=mount,
        tmp_path=tmp_path / "s2",
        backup_root=backup_root,
    )
    assert report.read_statuses_pushed == 1
    assert report.backup_path is None
