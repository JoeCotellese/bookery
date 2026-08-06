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


def _seed_kobo_db(path: Path, content_ids: list[str], *, series_id_column: bool = True) -> None:
    """KoboReader.sqlite with the columns both the pull and the series push touch.

    ``series_id_column=False`` models a device whose ``content`` table doesn't
    carry ``SeriesID`` at all, which is what makes the writer's UPDATE raise.
    """
    conn = sqlite3.connect(str(path))
    columns = [
        "ContentID            TEXT PRIMARY KEY",
        "BookID               TEXT",
        "ReadStatus           INTEGER",
        "___PercentRead       REAL",
        "DateLastRead         TEXT",
        "ChapterIDBookmarked  TEXT",
        "MimeType             TEXT",
        "Series               TEXT",
        "SeriesNumber         TEXT",
        "SeriesNumberFloat    REAL",
    ]
    if series_id_column:
        columns.append("SeriesID TEXT")
    conn.execute(f"CREATE TABLE content ({', '.join(columns)})")
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


def _series_number_float(db_path: Path, content_id: str) -> float | None:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT SeriesNumberFloat FROM content WHERE ContentID = ?",
            (content_id,),
        ).fetchone()[0]
    finally:
        conn.close()


def _seed_catalog(tmp_path: Path, *, indexless_series: bool = False):
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
    if indexless_series:
        epub_c = library / "Terry Pratchett" / "Mort" / "Mort.epub"
        epub_c.parent.mkdir(parents=True, exist_ok=True)
        epub_c.write_bytes(b"EPUB")
        catalog.add_book(
            BookMetadata(
                title="Mort",
                authors=["Terry Pratchett"],
                series="Discworld",
                series_index=None,
                source_path=epub_c,
            ),
            file_hash="hash-c",
            output_path=epub_c,
        )
    return conn, catalog


CID_A = "file:///mnt/onboard/Books/Robert Jordan/The Great Hunt/The Great Hunt.kepub.epub"
CID_B = "file:///mnt/onboard/Books/Le Guin/Earthsea/Earthsea.kepub.epub"
CID_C = "file:///mnt/onboard/Books/Terry Pratchett/Mort/Mort.kepub.epub"


def _run_sync(catalog, mount: Path, tmp_path: Path, *, backup_root: Path | None = None):
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
    # Firmware 4.45 keeps the position in both columns; a text-only write
    # leaves SeriesNumberFloat at 0.0 and the grouping reads wrong.
    assert _series_number_float(mount / ".kobo" / "KoboReader.sqlite", CID_A) == 2.0
    # The series-less book is left alone.
    assert _series_row(mount / ".kobo" / "KoboReader.sqlite", CID_B) == (None, None, None)


def test_series_without_an_index_writes_name_only(tmp_path: Path) -> None:
    """A book in a series with no position gets Series but a NULL number."""
    conn, catalog = _seed_catalog(tmp_path, indexless_series=True)
    mount = _build_fake_kobo_mount(tmp_path)
    db_path = mount / ".kobo" / "KoboReader.sqlite"
    _seed_kobo_db(db_path, [CID_A, CID_B, CID_C])

    report = _run_sync(catalog, mount, tmp_path)
    conn.close()

    assert report.series_pushed == 2
    assert _series_row(db_path, CID_C) == ("Discworld", None, "Discworld")
    assert _series_number_float(db_path, CID_C) is None


def test_series_push_takes_a_backup_first(tmp_path: Path) -> None:
    """With a backup root configured, the device DB is snapshotted before the write."""
    conn, catalog = _seed_catalog(tmp_path)
    mount = _build_fake_kobo_mount(tmp_path)
    _seed_kobo_db(mount / ".kobo" / "KoboReader.sqlite", [CID_A, CID_B])
    backup_root = tmp_path / "backups"

    report = _run_sync(catalog, mount, tmp_path, backup_root=backup_root)
    conn.close()

    assert report.series_pushed == 1
    assert report.backup_path is not None
    assert report.backup_path.is_file()
    assert report.backup_path.parent.name == "N428440071799"


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


def test_missing_device_db_skips_the_series_push(tmp_path: Path, caplog) -> None:
    """A mount with no KoboReader.sqlite is skipped, not an error."""
    conn, catalog = _seed_catalog(tmp_path)
    mount = _build_fake_kobo_mount(tmp_path)  # deliberately no KoboReader.sqlite
    assert not (mount / ".kobo" / "KoboReader.sqlite").exists()

    with caplog.at_level("WARNING", logger="bookery.device.kobo"):
        report = _run_sync(catalog, mount, tmp_path)
    conn.close()

    assert report.series_pushed == 0
    assert report.series_pending == 0
    assert report.series_push_failed == []
    assert any("skipping series push" in rec.message for rec in caplog.records)


def test_writer_rollback_surfaces_as_series_push_failed(tmp_path: Path) -> None:
    """A content table the UPDATE can't satisfy reports every book as failed."""
    conn, catalog = _seed_catalog(tmp_path)
    mount = _build_fake_kobo_mount(tmp_path)
    _seed_kobo_db(mount / ".kobo" / "KoboReader.sqlite", [CID_A, CID_B], series_id_column=False)

    report = _run_sync(catalog, mount, tmp_path)
    conn.close()

    assert report.series_pushed == 0
    assert [cid for cid, _ in report.series_push_failed] == [CID_A]
    assert "SeriesID" in report.series_push_failed[0][1]


def test_unreadable_device_db_surfaces_as_series_push_failed(tmp_path: Path, caplog) -> None:
    """An exception escaping the writer lands in the report instead of aborting the sync."""
    conn, catalog = _seed_catalog(tmp_path)
    mount = _build_fake_kobo_mount(tmp_path)
    # A KoboReader.sqlite that exists but isn't a database — the writer raises
    # before it can open a transaction, so push_series never returns a report.
    (mount / ".kobo" / "KoboReader.sqlite").write_bytes(b"not a sqlite file at all")

    with caplog.at_level("WARNING", logger="bookery.device.kobo"):
        report = _run_sync(catalog, mount, tmp_path)
    conn.close()

    assert report.series_pushed == 0
    assert [cid for cid, _ in report.series_push_failed] == [CID_A]
    assert any("Series push failed" in rec.message for rec in caplog.records)
    # The copy half of the sync still did its job.
    assert len(report.copied) == 2
