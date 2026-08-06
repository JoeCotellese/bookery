# ABOUTME: Unit tests for the kobo_writer series push — writes Series/SeriesNumber/
# ABOUTME: SeriesID/SeriesNumberFloat into KoboReader.sqlite rows for sideloaded books.

import hashlib
import sqlite3
from pathlib import Path

from bookery.device import kobo_writer
from bookery.device.kobo_writer import SeriesUpdate, push_series

CID = "file:///mnt/onboard/Bookery/Robert Jordan/The Great Hunt/The Great Hunt.kepub.epub"
CID_2 = "file:///mnt/onboard/Bookery/Robert Jordan/The Dragon Reborn/The Dragon Reborn.kepub.epub"

# A CHECK constraint gives us a row that fails its UPDATE at a chosen point in
# the batch, which a schema-shaped error can't do: a missing column fails on
# the very first row, before anything has been written, so nothing is left for
# a rollback to undo.
REJECTED_SERIES = "Series The Device Rejects"


def _seed_rejecting_content_table(db_path: Path, content_ids: list[str]) -> None:
    """content table whose UPDATE succeeds for every series but ``REJECTED_SERIES``."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        f"""
        CREATE TABLE content (
            ContentID     TEXT PRIMARY KEY,
            Series        TEXT CHECK (Series IS NULL OR Series != '{REJECTED_SERIES}'),
            SeriesNumber  TEXT,
            SeriesID      TEXT,
            ReadStatus    INTEGER
        )
        """
    )
    conn.executemany(
        "INSERT INTO content VALUES (?, NULL, NULL, NULL, 1)",
        [(cid,) for cid in content_ids],
    )
    conn.commit()
    conn.close()


class _KeepOpenConnection(sqlite3.Connection):
    """Connection whose ``close()`` is deferred until the test says so.

    ``push_series`` closes its connection in a ``finally``, and closing an
    sqlite3 connection discards uncommitted work — which would hide whether
    the writer actually rolled back. Suppressing close keeps the transaction
    state observable.
    """

    @classmethod
    def connect(cls, db_path: Path) -> "_KeepOpenConnection":
        return sqlite3.connect(f"file:{db_path}?mode=rw", uri=True, factory=cls)

    def close(self) -> None:
        pass

    def release(self) -> None:
        super().close()


def _seed_content_table(db_path: Path, rows: list[tuple], *, with_float: bool = False) -> None:
    """Minimal content table for series-writer tests.

    Each row is (ContentID, Series, SeriesNumber, SeriesID, ReadStatus).
    ReadStatus lets us assert the writer leaves unrelated columns alone.
    ``with_float`` adds the ``SeriesNumberFloat REAL`` column that firmware
    4.45 carries (rows then take a sixth value); leaving it off models an
    older device whose ``content`` table has no such column.
    """
    columns = [
        "ContentID     TEXT PRIMARY KEY",
        "Series        TEXT",
        "SeriesNumber  TEXT",
        "SeriesID      TEXT",
        "ReadStatus    INTEGER",
    ]
    if with_float:
        columns.append("SeriesNumberFloat REAL")
    conn = sqlite3.connect(str(db_path))
    conn.execute(f"CREATE TABLE content ({', '.join(columns)})")
    conn.executemany(
        f"INSERT INTO content VALUES ({', '.join('?' * len(columns))})",
        rows,
    )
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


def _float_row(db_path: Path, content_id: str) -> tuple:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT Series, SeriesNumber, SeriesID, SeriesNumberFloat"
            " FROM content WHERE ContentID = ?",
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

    def test_sqlite_error_rolls_back_earlier_writes_in_the_batch(self, tmp_path: Path) -> None:
        """A row that fails mid-batch undoes the rows already written before it."""
        db = tmp_path / "KoboReader.sqlite"
        _seed_rejecting_content_table(db, [CID, CID_2])
        sha_before = _file_sha(db)

        report = push_series(
            db_path=db,
            updates=[
                SeriesUpdate(content_id=CID, series="The Wheel of Time", series_number="2"),
                SeriesUpdate(content_id=CID_2, series=REJECTED_SERIES, series_number="1"),
            ],
        )

        assert report.pushed_count == 0
        assert report.unchanged_count == 0
        assert report.pending_count == 0
        assert [cid for cid, _ in report.failed] == [CID, CID_2]
        # The first row *did* get an UPDATE before the second one blew up; it
        # must be back to its pre-batch values.
        assert _row(db, CID) == (None, None, None, 1)
        assert _file_sha(db) == sha_before

    def test_rollback_leaves_no_open_transaction(self, tmp_path: Path, monkeypatch) -> None:
        """The failure path issues ROLLBACK rather than leaning on close().

        Closing a connection discards uncommitted work anyway, so file state
        alone cannot tell a real ROLLBACK from a dangling transaction. This
        test keeps the writer's connection open past ``push_series`` and looks
        at it directly: the batch must be undone *and* the transaction closed.
        """
        db = tmp_path / "KoboReader.sqlite"
        _seed_rejecting_content_table(db, [CID, CID_2])

        held = _KeepOpenConnection.connect(db)
        monkeypatch.setattr(kobo_writer, "open_kobo_db_rw", lambda _path: held)

        push_series(
            db_path=db,
            updates=[
                SeriesUpdate(content_id=CID, series="The Wheel of Time", series_number="2"),
                SeriesUpdate(content_id=CID_2, series=REJECTED_SERIES, series_number="1"),
            ],
        )

        try:
            assert held.in_transaction is False
            assert held.execute(
                "SELECT Series FROM content WHERE ContentID = ?", (CID,)
            ).fetchone() == (None,)
        finally:
            held.release()


class TestSeriesNumberFloat:
    """Firmware 4.45 keeps a REAL ``SeriesNumberFloat`` beside the TEXT column.

    Calibre's Kobo driver writes both; a row carrying ``SeriesNumber = '5'``
    and ``SeriesNumberFloat = 0.0`` is what bookery left on a real device
    before this column was written (#298).
    """

    def test_writes_float_beside_the_text_index(self, tmp_path: Path) -> None:
        db = tmp_path / "KoboReader.sqlite"
        _seed_content_table(db, [(CID, None, None, None, 1, None)], with_float=True)

        report = push_series(
            db_path=db,
            updates=[
                SeriesUpdate(content_id=CID, series="The Wheel of Time", series_number="2.5")
            ],
        )

        assert report.pushed_count == 1
        assert report.failed == []
        assert _float_row(db, CID) == ("The Wheel of Time", "2.5", "The Wheel of Time", 2.5)

    def test_stale_zero_float_is_healed(self, tmp_path: Path) -> None:
        """Text columns already correct but the float wrong is still a write."""
        db = tmp_path / "KoboReader.sqlite"
        _seed_content_table(
            db,
            [(CID, "The Wheel of Time", "2", "The Wheel of Time", 1, 0.0)],
            with_float=True,
        )

        report = push_series(
            db_path=db,
            updates=[SeriesUpdate(content_id=CID, series="The Wheel of Time", series_number="2")],
        )

        assert report.pushed_count == 1
        assert report.unchanged_count == 0
        assert _float_row(db, CID) == ("The Wheel of Time", "2", "The Wheel of Time", 2.0)

    def test_matching_float_counts_unchanged(self, tmp_path: Path) -> None:
        db = tmp_path / "KoboReader.sqlite"
        _seed_content_table(
            db,
            [(CID, "The Wheel of Time", "2", "The Wheel of Time", 1, 2.0)],
            with_float=True,
        )
        sha_before = _file_sha(db)

        report = push_series(
            db_path=db,
            updates=[SeriesUpdate(content_id=CID, series="The Wheel of Time", series_number="2")],
        )

        assert report.pushed_count == 0
        assert report.unchanged_count == 1
        assert _file_sha(db) == sha_before

    def test_series_without_number_writes_null_float(self, tmp_path: Path) -> None:
        db = tmp_path / "KoboReader.sqlite"
        _seed_content_table(db, [(CID, None, None, None, 1, 0.0)], with_float=True)

        report = push_series(
            db_path=db,
            updates=[SeriesUpdate(content_id=CID, series="Discworld", series_number=None)],
        )

        assert report.pushed_count == 1
        assert _float_row(db, CID) == ("Discworld", None, "Discworld", None)

    def test_device_without_the_column_degrades_to_text_only(self, tmp_path: Path) -> None:
        """Older firmware has no SeriesNumberFloat — the batch must not fail."""
        db = tmp_path / "KoboReader.sqlite"
        _seed_content_table(db, [(CID, None, None, None, 1)])

        report = push_series(
            db_path=db,
            updates=[SeriesUpdate(content_id=CID, series="The Wheel of Time", series_number="2")],
        )

        assert report.failed == []
        assert report.pushed_count == 1
        assert _row(db, CID) == ("The Wheel of Time", "2", "The Wheel of Time", 1)
