# ABOUTME: Integration test for the sync-time series push — a real sync writes
# ABOUTME: catalog series into KoboReader.sqlite content rows (#298).

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


def _seed_kobo_db(path: Path, content_ids: list[str]) -> None:
    """KoboReader.sqlite with the columns both the pull and the series push touch."""
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
            MimeType             TEXT,
            Series               TEXT,
            SeriesNumber         TEXT,
            SeriesID             TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO content (ContentID, ReadStatus, MimeType)"
        " VALUES (?, 0, 'application/x-kobo-epub+zip')",
        [(cid,) for cid in content_ids],
    )
    conn.commit()
    conn.close()


def _series_row(db_path: Path, content_id: str) -> tuple | None:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT Series, SeriesNumber, SeriesID FROM content WHERE ContentID = ?",
            (content_id,),
        ).fetchone()
    finally:
        conn.close()


def _seed_catalog(tmp_path: Path):
    db_path = tmp_path / "library.db"
    conn = open_library(db_path)
    catalog = LibraryCatalog(conn)

    library = tmp_path / "library"
    epub_a = library / "Robert Jordan" / "The Great Hunt" / "The Great Hunt.epub"
    epub_b = library / "Le Guin" / "Earthsea" / "Earthsea.epub"
    for path in (epub_a, epub_b):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"EPUB")

    catalog.add_book(
        BookMetadata(
            title="The Great Hunt",
            authors=["Robert Jordan"],
            series="The Wheel of Time",
            series_index=2.0,
            source_path=epub_a,
        ),
        file_hash="hash-a",
        output_path=epub_a,
    )
    catalog.add_book(
        BookMetadata(title="Earthsea", authors=["Le Guin"], source_path=epub_b),
        file_hash="hash-b",
        output_path=epub_b,
    )
    return conn, catalog


CID_A = "file:///mnt/onboard/Books/Robert Jordan/The Great Hunt/The Great Hunt.kepub.epub"
CID_B = "file:///mnt/onboard/Books/Le Guin/Earthsea/Earthsea.kepub.epub"


def _run_sync(catalog, mount: Path, tmp_path: Path):
    return sync_library_to_kobo(
        catalog=catalog,
        target=mount,
        cache=KepubCache(tmp_path / "kepub.db"),
        run_kepubify=_StubKepubify().run,
        kepubify_version=_StubKepubify().get_version,
        workspace_dir=tmp_path / "workspace",
        books_subdir="Books",
    )


def test_sync_pushes_series_into_device_db(tmp_path: Path) -> None:
    """Books with catalog series get content.Series/SeriesNumber/SeriesID."""
    conn, catalog = _seed_catalog(tmp_path)
    mount = _build_fake_kobo_mount(tmp_path)
    _seed_kobo_db(mount / ".kobo" / "KoboReader.sqlite", [CID_A, CID_B])

    report = _run_sync(catalog, mount, tmp_path)
    conn.close()

    assert report.series_pushed == 1
    assert report.series_push_failed == []
    assert _series_row(mount / ".kobo" / "KoboReader.sqlite", CID_A) == (
        "The Wheel of Time",
        "2",
        "The Wheel of Time",
    )
    # The series-less book is left alone.
    assert _series_row(mount / ".kobo" / "KoboReader.sqlite", CID_B) == (None, None, None)


def test_resync_reports_series_unchanged(tmp_path: Path) -> None:
    """A second sync doesn't rewrite rows that already carry the values."""
    conn, catalog = _seed_catalog(tmp_path)
    mount = _build_fake_kobo_mount(tmp_path)
    _seed_kobo_db(mount / ".kobo" / "KoboReader.sqlite", [CID_A, CID_B])

    _run_sync(catalog, mount, tmp_path)
    report = _run_sync(catalog, mount, tmp_path)
    conn.close()

    assert report.series_pushed == 0
    assert report.series_unchanged == 1


def test_unimported_book_counts_pending(tmp_path: Path) -> None:
    """A book the firmware hasn't indexed yet is pending, not failed."""
    conn, catalog = _seed_catalog(tmp_path)
    mount = _build_fake_kobo_mount(tmp_path)
    _seed_kobo_db(mount / ".kobo" / "KoboReader.sqlite", [CID_B])  # no row for A

    report = _run_sync(catalog, mount, tmp_path)
    conn.close()

    assert report.series_pushed == 0
    assert report.series_pending == 1
    assert report.series_push_failed == []


def test_no_status_push_skips_series_write(tmp_path: Path) -> None:
    """--no-status-push disables all device-DB writes, series included."""
    conn, catalog = _seed_catalog(tmp_path)
    mount = _build_fake_kobo_mount(tmp_path)
    _seed_kobo_db(mount / ".kobo" / "KoboReader.sqlite", [CID_A, CID_B])

    report = sync_library_to_kobo(
        catalog=catalog,
        target=mount,
        cache=KepubCache(tmp_path / "kepub.db"),
        run_kepubify=_StubKepubify().run,
        kepubify_version=_StubKepubify().get_version,
        workspace_dir=tmp_path / "workspace",
        books_subdir="Books",
        status_push_enabled=False,
    )
    conn.close()

    assert report.series_pushed == 0
    assert _series_row(mount / ".kobo" / "KoboReader.sqlite", CID_A) == (None, None, None)
