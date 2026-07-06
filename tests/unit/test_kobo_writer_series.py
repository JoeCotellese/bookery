# ABOUTME: Unit tests for the kobo_writer series push — writes Series/SeriesNumber/
# ABOUTME: SeriesID into KoboReader.sqlite content rows for sideloaded books.

import hashlib
import sqlite3
from pathlib import Path

from bookery.device.kobo_writer import SeriesUpdate, push_series

CID = "file:///mnt/onboard/Bookery/Robert Jordan/The Great Hunt/The Great Hunt.kepub.epub"


def _seed_content_table(db_path: Path, rows: list[tuple]) -> None:
    """Minimal content table for series-writer tests.

    Each row is (ContentID, Series, SeriesNumber, SeriesID, ReadStatus).
    ReadStatus lets us assert the writer leaves unrelated columns alone.
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE content (
            ContentID     TEXT PRIMARY KEY,
            Series        TEXT,
            SeriesNumber  TEXT,
            SeriesID      TEXT,
            ReadStatus    INTEGER
        )
        """
    )
    conn.executemany("INSERT INTO content VALUES (?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _row(db_path: Path, content_id: str) -> tuple:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT Series, SeriesNumber, SeriesID, ReadStatus FROM content WHERE ContentID = ?",
            (content_id,),
        ).fetchone()
    finally:
        conn.close()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestPushSeries:
    def test_writes_series_columns_for_existing_row(self, tmp_path: Path) -> None:
        """Series, SeriesNumber, and SeriesID land on the matching content row."""
        db = tmp_path / "KoboReader.sqlite"
        _seed_content_table(db, [(CID, None, None, None, 1)])

        report = push_series(
            db_path=db,
            updates=[SeriesUpdate(content_id=CID, series="The Wheel of Time", series_number="2")],
        )

        assert report.pushed_count == 1
        assert report.failed == []
        # SeriesID mirrors the series name (Calibre's sideload convention) and
        # unrelated columns are untouched.
        assert _row(db, CID) == ("The Wheel of Time", "2", "The Wheel of Time", 1)

    def test_series_without_number_leaves_number_null(self, tmp_path: Path) -> None:
        db = tmp_path / "KoboReader.sqlite"
        _seed_content_table(db, [(CID, None, None, None, 0)])

        report = push_series(
            db_path=db,
            updates=[SeriesUpdate(content_id=CID, series="Discworld", series_number=None)],
        )

        assert report.pushed_count == 1
        assert _row(db, CID) == ("Discworld", None, "Discworld", 0)

    def test_missing_row_counts_pending(self, tmp_path: Path) -> None:
        """A ContentID the firmware hasn't imported yet is pending, not a failure."""
        db = tmp_path / "KoboReader.sqlite"
        _seed_content_table(db, [])

        report = push_series(
            db_path=db,
            updates=[SeriesUpdate(content_id=CID, series="The Wheel of Time", series_number="2")],
        )

        assert report.pushed_count == 0
        assert report.pending_count == 1
        assert report.failed == []

    def test_matching_values_are_unchanged_and_skip_the_write(self, tmp_path: Path) -> None:
        """Re-pushing identical values must not rewrite the device DB."""
        db = tmp_path / "KoboReader.sqlite"
        _seed_content_table(db, [(CID, "The Wheel of Time", "2", "The Wheel of Time", 1)])
        sha_before = _file_sha(db)

        report = push_series(
            db_path=db,
            updates=[SeriesUpdate(content_id=CID, series="The Wheel of Time", series_number="2")],
        )

        assert report.pushed_count == 0
        assert report.unchanged_count == 1
        assert _file_sha(db) == sha_before

    def test_stale_values_are_overwritten(self, tmp_path: Path) -> None:
        db = tmp_path / "KoboReader.sqlite"
        _seed_content_table(db, [(CID, "Wrong Series", "9", "Wrong Series", 1)])

        report = push_series(
            db_path=db,
            updates=[SeriesUpdate(content_id=CID, series="The Wheel of Time", series_number="2")],
        )

        assert report.pushed_count == 1
        assert _row(db, CID)[:3] == ("The Wheel of Time", "2", "The Wheel of Time")

    def test_sqlite_error_rolls_back_batch(self, tmp_path: Path) -> None:
        """A schema surprise mid-batch rolls back every row and reports failures."""
        db = tmp_path / "KoboReader.sqlite"
        # No SeriesID column -> the UPDATE raises sqlite3.Error.
        conn = sqlite3.connect(str(db))
        conn.execute(
            "CREATE TABLE content (ContentID TEXT PRIMARY KEY, Series TEXT, SeriesNumber TEXT)"
        )
        conn.execute("INSERT INTO content VALUES (?, NULL, NULL)", (CID,))
        conn.commit()
        conn.close()
        sha_before = _file_sha(db)

        report = push_series(
            db_path=db,
            updates=[SeriesUpdate(content_id=CID, series="The Wheel of Time", series_number="2")],
        )

        assert report.pushed_count == 0
        assert len(report.failed) == 1
        assert _file_sha(db) == sha_before
