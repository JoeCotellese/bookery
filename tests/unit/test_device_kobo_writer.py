# ABOUTME: Unit tests for device/kobo_writer — the narrow R/W API to KoboReader.sqlite.
# ABOUTME: Covers connection opening, the push_read_status writer, and rollback safety.

import sqlite3
from pathlib import Path

import pytest

from bookery.device.kobo_writer import open_kobo_db_rw


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
