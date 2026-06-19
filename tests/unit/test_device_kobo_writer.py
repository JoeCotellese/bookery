# ABOUTME: Unit tests for device/kobo_writer — the narrow R/W API to KoboReader.sqlite.
# ABOUTME: Covers connection opening, the push_read_status writer, and rollback safety.

import hashlib
import sqlite3
from pathlib import Path

import pytest

from bookery.db.status import STATUS_FINISHED, STATUS_READING, STATUS_UNREAD
from bookery.device.kobo_writer import (
    ReadStatusUpdate,
    open_kobo_db_rw,
    push_read_status,
)

FROZEN_NOW = "2026-05-26T15:30:00"


def _seed_content_table(db_path: Path, rows: list[tuple]) -> None:
    """Build a minimal KoboReader.sqlite content table for writer tests.

    Each row is (ContentID, ReadStatus, ___PercentRead, DateLastRead,
    ___SyncTime, Synced). The extra columns let us assert the writer leaves
    them alone.
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE content (
            ContentID       TEXT PRIMARY KEY,
            ReadStatus      INTEGER,
            ___PercentRead  REAL,
            DateLastRead    TEXT,
            ___SyncTime     TEXT,
            Synced          INTEGER
        )
        """
    )
    conn.executemany("INSERT INTO content VALUES (?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestOpenKoboDbRw:
    def test_opens_existing_db_for_writes(self, tmp_path: Path) -> None:
        """An existing SQLite file opens in read-write mode."""
        db_path = tmp_path / "KoboReader.sqlite"
        # Seed an empty SQLite file so the URI has something to attach to.
        seed = sqlite3.connect(str(db_path))
        seed.execute("CREATE TABLE marker (id INTEGER)")
        seed.commit()
        seed.close()

        conn = open_kobo_db_rw(db_path)
        try:
            conn.execute("INSERT INTO marker (id) VALUES (1)")
            conn.commit()
            row = conn.execute("SELECT id FROM marker").fetchone()
        finally:
            conn.close()
        assert row[0] == 1

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        """A non-existent path raises sqlite3.OperationalError (no silent create)."""
        missing = tmp_path / "does-not-exist.sqlite"
        with pytest.raises(sqlite3.OperationalError):
            open_kobo_db_rw(missing)


class TestPushReadStatus:
    """The writer's central contract: status maps to the right columns, in one
    transaction, with DateLastRead stamped, leaving every other column alone.
    """

    _CID_A = "file:///mnt/onboard/Books/Asimov/Foundation/Foundation.kepub.epub"
    _CID_B = "file:///mnt/onboard/Books/LeGuin/Earthsea/Earthsea.kepub.epub"

    def _seed(self, tmp_path: Path) -> Path:
        db = tmp_path / "KoboReader.sqlite"
        _seed_content_table(
            db,
            [
                (self._CID_A, 0, 0.0, None, "2026-01-01T00:00:00", 1),
                (self._CID_B, 1, 33.0, "2026-02-15T10:00:00", "2026-01-01T00:00:00", 1),
            ],
        )
        return db

    def test_finished_sets_read_status_2_and_percent_100(self, tmp_path: Path) -> None:
        db = self._seed(tmp_path)
        report = push_read_status(
            db_path=db,
            updates=[ReadStatusUpdate(content_id=self._CID_A, status=STATUS_FINISHED)],
            now=lambda: FROZEN_NOW,
        )
        conn = sqlite3.connect(str(db))
        try:
            row = conn.execute(
                "SELECT ReadStatus, ___PercentRead, DateLastRead FROM content WHERE ContentID = ?",
                (self._CID_A,),
            ).fetchone()
        finally:
            conn.close()
        assert row == (2, 100.0, FROZEN_NOW)
        assert report.pushed_count == 1
        assert report.failed == []
        assert report.pull_only_count == 0

    def test_unread_sets_read_status_0_and_percent_0(self, tmp_path: Path) -> None:
        db = self._seed(tmp_path)
        push_read_status(
            db_path=db,
            updates=[ReadStatusUpdate(content_id=self._CID_B, status=STATUS_UNREAD)],
            now=lambda: FROZEN_NOW,
        )
        conn = sqlite3.connect(str(db))
        try:
            row = conn.execute(
                "SELECT ReadStatus, ___PercentRead, DateLastRead FROM content WHERE ContentID = ?",
                (self._CID_B,),
            ).fetchone()
        finally:
            conn.close()
        assert row == (0, 0.0, FROZEN_NOW)

    def test_reading_leaves_percent_untouched(self, tmp_path: Path) -> None:
        """STATUS_READING updates ReadStatus + DateLastRead, but not ___PercentRead."""
        db = self._seed(tmp_path)
        push_read_status(
            db_path=db,
            updates=[ReadStatusUpdate(content_id=self._CID_B, status=STATUS_READING)],
            now=lambda: FROZEN_NOW,
        )
        conn = sqlite3.connect(str(db))
        try:
            row = conn.execute(
                "SELECT ReadStatus, ___PercentRead, DateLastRead FROM content WHERE ContentID = ?",
                (self._CID_B,),
            ).fetchone()
        finally:
            conn.close()
        # ReadStatus and DateLastRead got stamped; ___PercentRead kept its seeded 33.0.
        assert row == (1, 33.0, FROZEN_NOW)

    def test_other_columns_untouched(self, tmp_path: Path) -> None:
        """Non-allow-listed columns (___SyncTime, Synced) keep their seeded values."""
        db = self._seed(tmp_path)
        push_read_status(
            db_path=db,
            updates=[ReadStatusUpdate(content_id=self._CID_A, status=STATUS_FINISHED)],
            now=lambda: FROZEN_NOW,
        )
        conn = sqlite3.connect(str(db))
        try:
            row = conn.execute(
                "SELECT ___SyncTime, Synced FROM content WHERE ContentID = ?",
                (self._CID_A,),
            ).fetchone()
        finally:
            conn.close()
        assert row == ("2026-01-01T00:00:00", 1)

    def test_unknown_content_id_counted_as_pull_only(self, tmp_path: Path) -> None:
        """ContentIDs the device doesn't know about don't fail — they're pull-only."""
        db = self._seed(tmp_path)
        report = push_read_status(
            db_path=db,
            updates=[
                ReadStatusUpdate(
                    content_id="file:///mnt/onboard/Books/Unknown.kepub.epub",
                    status=STATUS_FINISHED,
                ),
                ReadStatusUpdate(content_id=self._CID_A, status=STATUS_FINISHED),
            ],
            now=lambda: FROZEN_NOW,
        )
        assert report.pushed_count == 1
        assert report.pull_only_count == 1
        assert report.failed == []

    def test_rollback_on_error_leaves_db_unchanged(self, tmp_path: Path) -> None:
        """Any sqlite3 error mid-batch rolls back the whole transaction.

        We install a BEFORE-UPDATE trigger that aborts when ContentID matches
        the second row, then hash the DB. The trigger fires partway through
        the writer's batch — the writer must rollback the first row's update
        (which succeeded against the trigger) so the file hash is unchanged.
        """
        db = self._seed(tmp_path)
        seed_conn = sqlite3.connect(str(db))
        try:
            seed_conn.execute(
                "CREATE TRIGGER fail_on_b BEFORE UPDATE ON content "
                f"WHEN NEW.ContentID = '{self._CID_B}' "
                "BEGIN SELECT RAISE(ABORT, 'forced'); END"
            )
            seed_conn.commit()
        finally:
            seed_conn.close()
        pre_hash = _file_sha(db)

        report = push_read_status(
            db_path=db,
            updates=[
                ReadStatusUpdate(content_id=self._CID_A, status=STATUS_FINISHED),
                ReadStatusUpdate(content_id=self._CID_B, status=STATUS_FINISHED),
            ],
            now=lambda: FROZEN_NOW,
        )
        assert report.pushed_count == 0
        assert len(report.failed) >= 1
        assert _file_sha(db) == pre_hash

    def test_empty_updates_is_a_noop(self, tmp_path: Path) -> None:
        db = self._seed(tmp_path)
        pre_hash = _file_sha(db)
        report = push_read_status(db_path=db, updates=[], now=lambda: FROZEN_NOW)
        assert report.pushed_count == 0
        assert report.pull_only_count == 0
        assert report.failed == []
        assert _file_sha(db) == pre_hash

    def test_single_transaction_all_or_nothing(self, tmp_path: Path) -> None:
        """If the writer commits, all rows reflect the same now() stamp atomically."""
        db = self._seed(tmp_path)
        push_read_status(
            db_path=db,
            updates=[
                ReadStatusUpdate(content_id=self._CID_A, status=STATUS_FINISHED),
                ReadStatusUpdate(content_id=self._CID_B, status=STATUS_FINISHED),
            ],
            now=lambda: FROZEN_NOW,
        )
        conn = sqlite3.connect(str(db))
        try:
            rows = conn.execute("SELECT DateLastRead FROM content ORDER BY ContentID").fetchall()
        finally:
            conn.close()
        assert all(r[0] == FROZEN_NOW for r in rows)
