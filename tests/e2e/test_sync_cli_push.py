# ABOUTME: End-to-end CLI tests for the P2 status push — `bookery sync kobo`
# ABOUTME: with read-status writes, --no-status-push, and the Rich output.

import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.db.status import STATUS_FINISHED
from bookery.metadata.types import BookMetadata


def _fake_kepubify(payload: bytes = b"FAKE-KEPUB"):
    def runner(cmd, **_kwargs):
        if "--version" in cmd:
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="kepubify v4.4.0\n", stderr=""
            )
        out = Path(cmd[cmd.index("-o") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(payload)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    return runner


def _seed_kobo_db(path: Path, content_id: str, read_status: int = 0) -> None:
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
        "INSERT INTO content VALUES (?, NULL, ?, 0.0, '2026-05-20T10:00:00', NULL, ?)",
        (content_id, read_status, "application/x-kobo-epub+zip"),
    )
    conn.commit()
    conn.close()


def _seed_kobo_db_with_series(path: Path, content_ids: list[str]) -> None:
    """Device DB shaped like firmware 4.45 — the series columns included."""
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
            SeriesNumberFloat    REAL,
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


def _make_kobo_root(tmp_path: Path) -> Path:
    root = tmp_path / "kobo"
    root.mkdir()
    kobo_dir = root / ".kobo"
    kobo_dir.mkdir()
    (kobo_dir / "version").write_text("N428440071799,4.45.23684\n")
    return root


def _seed_catalog(db_path: Path, library: Path) -> int:
    epub = library / "Some Author" / "Some Title" / "Some Title.epub"
    epub.parent.mkdir(parents=True, exist_ok=True)
    epub.write_bytes(b"FAKE-EPUB")
    conn = open_library(db_path)
    try:
        catalog = LibraryCatalog(conn)
        book_id = catalog.add_book(
            BookMetadata(title="Some Title", authors=["Some Author"], source_path=epub),
            file_hash="seed-hash",
            output_path=epub,
        )
    finally:
        conn.close()
    return book_id


def _seed_series_catalog(db_path: Path, library: Path) -> None:
    epub = library / "Robert Jordan" / "The Great Hunt" / "The Great Hunt.epub"
    epub.parent.mkdir(parents=True, exist_ok=True)
    epub.write_bytes(b"FAKE-EPUB")
    conn = open_library(db_path)
    try:
        LibraryCatalog(conn).add_book(
            BookMetadata(
                title="The Great Hunt",
                authors=["Robert Jordan"],
                series="The Wheel of Time",
                series_index=2.0,
                source_path=epub,
            ),
            file_hash="series-hash",
            output_path=epub,
        )
    finally:
        conn.close()


SERIES_CONTENT_ID = (
    "file:///mnt/onboard/Bookery/Robert Jordan/The Great Hunt/The Great Hunt.kepub.epub"
)


def _run_cli(*args: str):
    runner = CliRunner()
    with (
        patch("bookery.device.kepubify.shutil.which", return_value="/usr/bin/kepubify"),
        patch("bookery.device.kepubify.subprocess.run", side_effect=_fake_kepubify()),
    ):
        return runner.invoke(cli, list(args))


def test_push_renders_in_cli_output(tmp_path: Path) -> None:
    db_path = tmp_path / "lib.db"
    library = tmp_path / "library"
    book_id = _seed_catalog(db_path, library)
    target = _make_kobo_root(tmp_path)
    content_id = "/mnt/onboard/Bookery/Some Author/Some Title/Some Title.kepub.epub"
    _seed_kobo_db(target / ".kobo" / "KoboReader.sqlite", f"file://{content_id}")

    # First sync populates device_files so the resolver can match next time.
    first = _run_cli(
        "sync",
        "kobo",
        "--target",
        str(target),
        "--db",
        str(db_path),
        "--data-dir",
        str(tmp_path / "data"),
    )
    assert first.exit_code == 0, first.output

    # User marks finished in bookery (timestamp strictly later than device).
    conn = open_library(db_path)
    try:
        catalog = LibraryCatalog(conn)
        catalog.set_book_status(
            book_id=book_id,
            status=STATUS_FINISHED,
            updated_at="2026-05-26T11:00:00",
        )
    finally:
        conn.close()

    second = _run_cli(
        "sync",
        "kobo",
        "--target",
        str(target),
        "--db",
        str(db_path),
        "--data-dir",
        str(tmp_path / "data"),
    )
    assert second.exit_code == 0, second.output
    assert "Pushed 1 read-status update" in second.output
    assert "Backup:" in second.output
    # Device row actually changed.
    row = (
        sqlite3.connect(str(target / ".kobo" / "KoboReader.sqlite"))
        .execute(
            "SELECT ReadStatus FROM content WHERE ContentID = ?",
            (f"file://{content_id}",),
        )
        .fetchone()
    )
    assert row[0] == 2


def test_no_status_push_flag_skips_writer(tmp_path: Path) -> None:
    db_path = tmp_path / "lib.db"
    library = tmp_path / "library"
    book_id = _seed_catalog(db_path, library)
    target = _make_kobo_root(tmp_path)
    content_id = "/mnt/onboard/Bookery/Some Author/Some Title/Some Title.kepub.epub"
    _seed_kobo_db(target / ".kobo" / "KoboReader.sqlite", f"file://{content_id}")

    _run_cli(
        "sync",
        "kobo",
        "--target",
        str(target),
        "--db",
        str(db_path),
        "--data-dir",
        str(tmp_path / "data"),
    )
    conn = open_library(db_path)
    try:
        catalog = LibraryCatalog(conn)
        catalog.set_book_status(
            book_id=book_id,
            status=STATUS_FINISHED,
            updated_at="2026-05-26T11:00:00",
        )
    finally:
        conn.close()

    result = _run_cli(
        "sync",
        "kobo",
        "--target",
        str(target),
        "--db",
        str(db_path),
        "--data-dir",
        str(tmp_path / "data"),
        "--no-status-push",
    )
    assert result.exit_code == 0, result.output
    assert "Pushed" not in result.output
    assert "Backup" not in result.output
    # Device row is unchanged — still Unread.
    row = (
        sqlite3.connect(str(target / ".kobo" / "KoboReader.sqlite"))
        .execute(
            "SELECT ReadStatus FROM content WHERE ContentID = ?",
            (f"file://{content_id}",),
        )
        .fetchone()
    )
    assert row[0] == 0


def test_series_push_renders_in_cli_output(tmp_path: Path) -> None:
    """`sync kobo` tells the user how many books got series metadata."""
    db_path = tmp_path / "lib.db"
    library = tmp_path / "library"
    _seed_series_catalog(db_path, library)
    target = _make_kobo_root(tmp_path)
    _seed_kobo_db_with_series(target / ".kobo" / "KoboReader.sqlite", [SERIES_CONTENT_ID])

    result = _run_cli(
        "sync",
        "kobo",
        "--target",
        str(target),
        "--db",
        str(db_path),
        "--data-dir",
        str(tmp_path / "data"),
    )

    assert result.exit_code == 0, result.output
    assert "Pushed series metadata for 1 book(s)" in result.output
    assert "pending device import" not in result.output
    row = (
        sqlite3.connect(str(target / ".kobo" / "KoboReader.sqlite"))
        .execute(
            "SELECT Series, SeriesNumber, SeriesNumberFloat, SeriesID"
            " FROM content WHERE ContentID = ?",
            (SERIES_CONTENT_ID,),
        )
        .fetchone()
    )
    assert row == ("The Wheel of Time", "2", 2.0, "The Wheel of Time")


def test_series_push_reports_books_awaiting_device_import(tmp_path: Path) -> None:
    """A book the firmware hasn't indexed yet is shown as pending, not failed."""
    db_path = tmp_path / "lib.db"
    library = tmp_path / "library"
    _seed_series_catalog(db_path, library)
    target = _make_kobo_root(tmp_path)
    _seed_kobo_db_with_series(target / ".kobo" / "KoboReader.sqlite", [])

    result = _run_cli(
        "sync",
        "kobo",
        "--target",
        str(target),
        "--db",
        str(db_path),
        "--data-dir",
        str(tmp_path / "data"),
    )

    assert result.exit_code == 0, result.output
    assert "Pushed series metadata for 0 book(s)" in result.output
    assert "pending device import: 1" in result.output


def test_series_push_failure_is_listed_per_book(tmp_path: Path) -> None:
    """A device DB the writer can't use is reported, and the sync still succeeds."""
    db_path = tmp_path / "lib.db"
    library = tmp_path / "library"
    _seed_series_catalog(db_path, library)
    target = _make_kobo_root(tmp_path)
    (target / ".kobo" / "KoboReader.sqlite").write_bytes(b"not a sqlite file at all")

    result = _run_cli(
        "sync",
        "kobo",
        "--target",
        str(target),
        "--db",
        str(db_path),
        "--data-dir",
        str(tmp_path / "data"),
    )

    assert result.exit_code == 0, result.output
    assert "Series push failed for 1 book(s):" in result.output
    assert "The Great Hunt.kepub.epub" in result.output
    assert "Pushed series metadata" not in result.output


def test_no_status_push_flag_skips_the_series_write(tmp_path: Path) -> None:
    """--no-status-push turns off series grouping too, as its help text says."""
    db_path = tmp_path / "lib.db"
    library = tmp_path / "library"
    _seed_series_catalog(db_path, library)
    target = _make_kobo_root(tmp_path)
    _seed_kobo_db_with_series(target / ".kobo" / "KoboReader.sqlite", [SERIES_CONTENT_ID])

    result = _run_cli(
        "sync",
        "kobo",
        "--target",
        str(target),
        "--db",
        str(db_path),
        "--data-dir",
        str(tmp_path / "data"),
        "--no-status-push",
    )

    assert result.exit_code == 0, result.output
    assert "Pushed series metadata" not in result.output
    row = (
        sqlite3.connect(str(target / ".kobo" / "KoboReader.sqlite"))
        .execute(
            "SELECT Series, SeriesNumber FROM content WHERE ContentID = ?",
            (SERIES_CONTENT_ID,),
        )
        .fetchone()
    )
    assert row == (None, None)


def test_no_status_push_help_names_series_grouping() -> None:
    """The flag turns off more than read-status; its help must say so."""
    result = CliRunner().invoke(cli, ["sync", "kobo", "--help"])

    assert result.exit_code == 0, result.output
    assert "series" in result.output
