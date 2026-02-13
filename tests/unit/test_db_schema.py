# ABOUTME: Unit tests for database schema creation and connection management.
# ABOUTME: Validates table structure, indexes, FTS5, WAL mode, and default paths.

import sqlite3
from pathlib import Path

import pytest

from bookery.db.connection import DEFAULT_DB_PATH, open_library


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    """Provide a temporary database path."""
    return tmp_path / "test_library.db"


class TestOpenLibrary:
    """Tests for open_library() connection factory."""

    def test_creates_database_file(self, db_path: Path) -> None:
        """Calling open_library creates a .db file at the given path."""
        conn = open_library(db_path)
        conn.close()
        assert db_path.exists()

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Creates parent directories if they don't exist."""
        nested = tmp_path / "deep" / "nested" / "library.db"
        conn = open_library(nested)
        conn.close()
        assert nested.exists()

    def test_creates_books_table(self, db_path: Path) -> None:
        """The books table exists with expected columns."""
        conn = open_library(db_path)
        cursor = conn.execute("PRAGMA table_info(books)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()

        expected = {
            "id",
            "title",
            "authors",
            "author_sort",
            "language",
            "publisher",
            "isbn",
            "description",
            "series",
            "series_index",
            "identifiers",
            "source_path",
            "output_path",
            "file_hash",
            "date_added",
            "date_modified",
        }
        assert expected == columns

    def test_creates_fts_table(self, db_path: Path) -> None:
        """The books_fts FTS5 virtual table exists."""
        conn = open_library(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='books_fts'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_creates_schema_version_table(self, db_path: Path) -> None:
        """schema_version table exists with latest version after migrations."""
        conn = open_library(db_path)
        cursor = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        assert row is not None
        assert row[0] == 2

    def test_creates_indexes(self, db_path: Path) -> None:
        """Expected indexes exist on the books table."""
        conn = open_library(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='books'"
        )
        index_names = {row[0] for row in cursor.fetchall()}
        conn.close()

        assert "idx_books_file_hash" in index_names
        assert "idx_books_isbn" in index_names
        assert "idx_books_series" in index_names

    def test_default_path(self) -> None:
        """Default path resolves to ~/.bookery/library.db."""
        expected = Path.home() / ".bookery" / "library.db"
        assert expected == DEFAULT_DB_PATH

    def test_reopen_existing_database(self, db_path: Path) -> None:
        """Opening an existing DB does not recreate or destroy data."""
        conn = open_library(db_path)
        conn.execute(
            "INSERT INTO books (title, source_path, file_hash) "
            "VALUES ('Test Book', '/tmp/test.epub', 'abc123')"
        )
        conn.commit()
        conn.close()

        conn2 = open_library(db_path)
        cursor = conn2.execute("SELECT title FROM books")
        row = cursor.fetchone()
        conn2.close()
        assert row is not None
        assert row[0] == "Test Book"

    def test_connection_is_wal_mode(self, db_path: Path) -> None:
        """WAL journal mode is enabled for better concurrent read performance."""
        conn = open_library(db_path)
        cursor = conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        conn.close()
        assert mode == "wal"

    def test_connection_has_row_factory(self, db_path: Path) -> None:
        """Connection uses sqlite3.Row factory for dict-like access."""
        conn = open_library(db_path)
        assert conn.row_factory == sqlite3.Row
        conn.close()
