# ABOUTME: Unit tests for device/kobo_backup — per-device-per-day KoboReader.sqlite snapshots.
# ABOUTME: Covers create-on-first-call, idempotent same-day, rotation to 14 most recent.

import datetime as _dt
from pathlib import Path

from bookery.device.kobo_backup import backup_kobo_db


def _seed_source(tmp_path: Path, content: bytes = b"FAKE-KOBO-DB") -> Path:
    src = tmp_path / "KoboReader.sqlite"
    src.write_bytes(content)
    return src


class TestBackupKoboDb:
    SERIAL = "N428440071799"

    def test_first_call_creates_backup_file(self, tmp_path: Path) -> None:
        src = _seed_source(tmp_path)
        backup_root = tmp_path / "backups"

        result = backup_kobo_db(
            source_db=src,
            backup_root=backup_root,
            device_serial=self.SERIAL,
            now=_dt.datetime(2026, 5, 26, 10, 30, 0),
        )

        assert result is not None
        assert result.parent == backup_root / self.SERIAL
        assert result.exists()
        assert result.read_bytes() == b"FAKE-KOBO-DB"
        # Naming includes ISO date + time so multiple per-day backups still sort.
        assert "2026-05-26" in result.name
        assert result.suffix == ".sqlite"

    def test_same_day_second_call_is_idempotent(self, tmp_path: Path) -> None:
        """Two calls on the same calendar day return the same path without
        re-copying — the snapshot is "first mutating sync per device-day".
        """
        src = _seed_source(tmp_path)
        backup_root = tmp_path / "backups"

        first = backup_kobo_db(
            source_db=src,
            backup_root=backup_root,
            device_serial=self.SERIAL,
            now=_dt.datetime(2026, 5, 26, 10, 30, 0),
        )
        # Mutate the source between calls — second call should NOT re-copy.
        src.write_bytes(b"NEWER-BYTES")
        second = backup_kobo_db(
            source_db=src,
            backup_root=backup_root,
            device_serial=self.SERIAL,
            now=_dt.datetime(2026, 5, 26, 18, 00, 0),
        )

        assert first == second
        assert second is not None
        # First call's bytes are preserved — we don't overwrite the day's snapshot.
        assert second.read_bytes() == b"FAKE-KOBO-DB"

    def test_next_day_creates_new_backup(self, tmp_path: Path) -> None:
        src = _seed_source(tmp_path)
        backup_root = tmp_path / "backups"

        first = backup_kobo_db(
            source_db=src,
            backup_root=backup_root,
            device_serial=self.SERIAL,
            now=_dt.datetime(2026, 5, 26, 10, 30, 0),
        )
        src.write_bytes(b"DAY-TWO")
        second = backup_kobo_db(
            source_db=src,
            backup_root=backup_root,
            device_serial=self.SERIAL,
            now=_dt.datetime(2026, 5, 27, 9, 0, 0),
        )

        assert first != second
        assert second is not None
        assert second.read_bytes() == b"DAY-TWO"
        siblings = sorted((backup_root / self.SERIAL).iterdir())
        assert len(siblings) == 2

    def test_rotation_keeps_14_most_recent(self, tmp_path: Path) -> None:
        src = _seed_source(tmp_path)
        backup_root = tmp_path / "backups"

        # 16 simulated daily syncs. After day 15 we expect 14 files (the
        # 14 most recent — days 2..15 — kept; days 0..1 evicted).
        for day in range(16):
            backup_kobo_db(
                source_db=src,
                backup_root=backup_root,
                device_serial=self.SERIAL,
                now=_dt.datetime(2026, 5, 1, 10, 0, 0) + _dt.timedelta(days=day),
            )

        snapshots = sorted((backup_root / self.SERIAL).iterdir())
        assert len(snapshots) == 14
        # Oldest remaining should be day 2 (2026-05-03), newest day 15 (2026-05-16).
        assert "2026-05-03" in snapshots[0].name
        assert "2026-05-16" in snapshots[-1].name

    def test_missing_source_returns_none(self, tmp_path: Path) -> None:
        """Best-effort: a missing source file logs but doesn't raise."""
        missing = tmp_path / "nope.sqlite"
        result = backup_kobo_db(
            source_db=missing,
            backup_root=tmp_path / "backups",
            device_serial=self.SERIAL,
            now=_dt.datetime(2026, 5, 26, 10, 0, 0),
        )
        assert result is None

    def test_corrupted_backup_dir_does_not_raise(self, tmp_path: Path) -> None:
        """If <backup_root>/<serial> exists as a file (not a directory),
        the function returns None instead of blowing up — pushes still go.
        """
        src = _seed_source(tmp_path)
        backup_root = tmp_path / "backups"
        backup_root.mkdir()
        # Plant a regular file where the serial directory should live.
        (backup_root / self.SERIAL).write_text("not a directory")

        result = backup_kobo_db(
            source_db=src,
            backup_root=backup_root,
            device_serial=self.SERIAL,
            now=_dt.datetime(2026, 5, 26, 10, 0, 0),
        )
        assert result is None

    def test_separate_devices_get_separate_dirs(self, tmp_path: Path) -> None:
        src = _seed_source(tmp_path)
        backup_root = tmp_path / "backups"
        a = backup_kobo_db(
            source_db=src,
            backup_root=backup_root,
            device_serial="DEV-A",
            now=_dt.datetime(2026, 5, 26, 10, 0, 0),
        )
        b = backup_kobo_db(
            source_db=src,
            backup_root=backup_root,
            device_serial="DEV-B",
            now=_dt.datetime(2026, 5, 26, 10, 0, 0),
        )
        assert a is not None
        assert b is not None
        assert a.parent.name == "DEV-A"
        assert b.parent.name == "DEV-B"
