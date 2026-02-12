# ABOUTME: Integration tests for database lifecycle — create, insert, reopen, query.
# ABOUTME: Validates that data persists across connection open/close cycles.

from pathlib import Path

from bookery.db.connection import open_library


class TestDatabaseLifecycle:
    """Integration tests for full DB lifecycle."""

    def test_create_insert_reopen_query(self, tmp_path: Path) -> None:
        """Create DB, insert a row, close, reopen, verify row persists."""
        db_path = tmp_path / "lifecycle.db"

        conn = open_library(db_path)
        conn.execute(
            "INSERT INTO books (title, authors, source_path, file_hash) "
            "VALUES (?, ?, ?, ?)",
            ("The Name of the Rose", '["Umberto Eco"]', "/books/rose.epub", "hash1"),
        )
        conn.commit()
        conn.close()

        conn2 = open_library(db_path)
        cursor = conn2.execute("SELECT title, authors FROM books WHERE file_hash = ?", ("hash1",))
        row = cursor.fetchone()
        conn2.close()

        assert row is not None
        assert row["title"] == "The Name of the Rose"
        assert row["authors"] == '["Umberto Eco"]'

    def test_schema_version_persists(self, tmp_path: Path) -> None:
        """Schema version is written once and persists across reopens."""
        db_path = tmp_path / "version.db"

        conn = open_library(db_path)
        conn.close()

        conn2 = open_library(db_path)
        cursor = conn2.execute("SELECT COUNT(*) FROM schema_version")
        count = cursor.fetchone()[0]
        conn2.close()

        # Should still be 1 — not re-inserted on reopen
        assert count == 1

    def test_fts_sync_on_insert(self, tmp_path: Path) -> None:
        """FTS5 table is updated when a row is inserted into books."""
        db_path = tmp_path / "fts.db"

        conn = open_library(db_path)
        conn.execute(
            "INSERT INTO books (title, authors, description, source_path, file_hash) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                "Foucault's Pendulum", '["Umberto Eco"]',
                "A conspiracy thriller.", "/books/fp.epub", "hash2",
            ),
        )
        conn.commit()

        cursor = conn.execute(
            "SELECT rowid FROM books_fts WHERE books_fts MATCH ?", ("conspiracy",)
        )
        row = cursor.fetchone()
        conn.close()

        assert row is not None
