# ABOUTME: Unit tests for the schema migration runner.
# ABOUTME: Validates that migrations apply sequentially and are idempotent.

import sqlite3
from pathlib import Path

import pytest

from bookery.db.connection import _apply_migrations, _get_schema_version, open_library
from bookery.db.schema import MIGRATIONS


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    """Provide a temporary database path."""
    return tmp_path / "test_migration.db"


class TestMigrations:
    """Tests for the migration runner."""

    def test_fresh_db_has_latest_version(self, db_path: Path) -> None:
        """A fresh database should have all migrations applied."""
        conn = open_library(db_path)
        version = _get_schema_version(conn)
        conn.close()
        assert version == 2

    def test_migrations_list_is_ordered(self) -> None:
        """MIGRATIONS list has strictly increasing version numbers."""
        versions = [v for v, _ in MIGRATIONS]
        assert versions == sorted(versions)
        assert len(versions) == len(set(versions))

    def test_migration_creates_tags_table(self, db_path: Path) -> None:
        """V2 migration creates the tags table."""
        conn = open_library(db_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tags'")
        assert cursor.fetchone() is not None
        conn.close()

    def test_migration_creates_book_tags_table(self, db_path: Path) -> None:
        """V2 migration creates the book_tags table."""
        conn = open_library(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='book_tags'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_tags_table_has_nocase_collation(self, db_path: Path) -> None:
        """Tags name column uses NOCASE collation to prevent duplicates."""
        conn = open_library(db_path)
        # Insert mixed-case tags — second should fail on UNIQUE
        conn.execute("INSERT INTO tags (name) VALUES ('Fiction')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO tags (name) VALUES ('fiction')")
        conn.close()

    def test_book_tags_cascade_on_book_delete(self, db_path: Path) -> None:
        """Deleting a book cascades to remove book_tags associations."""
        conn = open_library(db_path)
        conn.execute(
            "INSERT INTO books (title, source_path, file_hash) "
            "VALUES ('Test', '/tmp/t.epub', 'hash1')"
        )
        conn.execute("INSERT INTO tags (name) VALUES ('sci-fi')")
        conn.execute("INSERT INTO book_tags (book_id, tag_id) VALUES (1, 1)")
        conn.commit()

        conn.execute("DELETE FROM books WHERE id = 1")
        conn.commit()

        cursor = conn.execute("SELECT COUNT(*) FROM book_tags")
        assert cursor.fetchone()[0] == 0
        conn.close()

    def test_book_tags_cascade_on_tag_delete(self, db_path: Path) -> None:
        """Deleting a tag cascades to remove book_tags associations."""
        conn = open_library(db_path)
        conn.execute(
            "INSERT INTO books (title, source_path, file_hash) "
            "VALUES ('Test', '/tmp/t.epub', 'hash1')"
        )
        conn.execute("INSERT INTO tags (name) VALUES ('fantasy')")
        conn.execute("INSERT INTO book_tags (book_id, tag_id) VALUES (1, 1)")
        conn.commit()

        conn.execute("DELETE FROM tags WHERE id = 1")
        conn.commit()

        cursor = conn.execute("SELECT COUNT(*) FROM book_tags")
        assert cursor.fetchone()[0] == 0
        conn.close()

    def test_apply_migrations_is_idempotent(self, db_path: Path) -> None:
        """Running migrations twice does not raise or change version."""
        conn = open_library(db_path)
        version_before = _get_schema_version(conn)
        _apply_migrations(conn)
        version_after = _get_schema_version(conn)
        conn.close()
        assert version_before == version_after

    def test_v1_db_upgrades_to_v2(self, db_path: Path) -> None:
        """A V1-only database upgrades to V2 when opened."""
        import sqlite3

        from bookery.db.schema import SCHEMA_V1

        # Create a V1-only database manually
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA_V1)
        conn.close()

        # Now open with bookery — should auto-migrate
        conn = open_library(db_path)
        version = _get_schema_version(conn)
        assert version == 2

        # Tags table should exist
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tags'")
        assert cursor.fetchone() is not None
        conn.close()

    def test_v1_data_preserved_after_migration(self, db_path: Path) -> None:
        """Books added under V1 survive the V2 migration."""
        import sqlite3

        from bookery.db.schema import SCHEMA_V1

        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA_V1)
        conn.execute(
            "INSERT INTO books (title, source_path, file_hash) "
            "VALUES ('Preserved Book', '/tmp/p.epub', 'phash')"
        )
        conn.commit()
        conn.close()

        conn = open_library(db_path)
        cursor = conn.execute("SELECT title FROM books WHERE file_hash = 'phash'")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "Preserved Book"
        conn.close()
