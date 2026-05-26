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
            BookMetadata(
                title="Some Title", authors=["Some Author"], source_path=epub
            ),
            file_hash="seed-hash",
            output_path=epub,
        )
    finally:
        conn.close()
    return book_id


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
        "sync", "kobo",
        "--target", str(target),
        "--db", str(db_path),
        "--data-dir", str(tmp_path / "data"),
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
        "sync", "kobo",
        "--target", str(target),
        "--db", str(db_path),
        "--data-dir", str(tmp_path / "data"),
    )
    assert second.exit_code == 0, second.output
    assert "Pushed 1 read-status update" in second.output
    assert "Backup:" in second.output
    # Device row actually changed.
    row = sqlite3.connect(str(target / ".kobo" / "KoboReader.sqlite")).execute(
        "SELECT ReadStatus FROM content WHERE ContentID = ?",
        (f"file://{content_id}",),
    ).fetchone()
    assert row[0] == 2


def test_no_status_push_flag_skips_writer(tmp_path: Path) -> None:
    db_path = tmp_path / "lib.db"
    library = tmp_path / "library"
    book_id = _seed_catalog(db_path, library)
    target = _make_kobo_root(tmp_path)
    content_id = "/mnt/onboard/Bookery/Some Author/Some Title/Some Title.kepub.epub"
    _seed_kobo_db(target / ".kobo" / "KoboReader.sqlite", f"file://{content_id}")

    _run_cli(
        "sync", "kobo",
        "--target", str(target),
        "--db", str(db_path),
        "--data-dir", str(tmp_path / "data"),
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
        "sync", "kobo",
        "--target", str(target),
        "--db", str(db_path),
        "--data-dir", str(tmp_path / "data"),
        "--no-status-push",
    )
    assert result.exit_code == 0, result.output
    assert "Pushed" not in result.output
    assert "Backup" not in result.output
    # Device row is unchanged — still Unread.
    row = sqlite3.connect(str(target / ".kobo" / "KoboReader.sqlite")).execute(
        "SELECT ReadStatus FROM content WHERE ContentID = ?",
        (f"file://{content_id}",),
    ).fetchone()
    assert row[0] == 0
