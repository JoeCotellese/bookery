# ABOUTME: Unit tests for SCHEMA_V3 migration (genres tables and subjects column).
# ABOUTME: Validates table creation, genre seeding, and mapping serialization.

import json
from pathlib import Path

import pytest

from bookery.db.connection import open_library
from bookery.db.mapping import metadata_to_row, row_to_metadata
from bookery.metadata.genres import CANONICAL_GENRES
from bookery.metadata.types import BookMetadata


@pytest.fixture()
def conn(tmp_path: Path):
    """Open a fresh library database with all migrations applied."""
    connection = open_library(tmp_path / "v3_test.db")
    yield connection
    connection.close()


class TestV3MigrationTables:
    """Tests for the V3 migration DDL."""

    def test_genres_table_created(self, conn) -> None:
        """V3 migration creates the genres table."""
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='genres'"
        )
        assert cursor.fetchone() is not None

    def test_genres_seeded_with_14_rows(self, conn) -> None:
        """Genres table is seeded with 14 canonical genre entries."""
        cursor = conn.execute("SELECT COUNT(*) FROM genres")
        assert cursor.fetchone()[0] == 14

    def test_genres_contain_all_canonical(self, conn) -> None:
        """All canonical genres are present in the genres table."""
        cursor = conn.execute("SELECT name FROM genres ORDER BY name")
        db_genres = {row[0] for row in cursor.fetchall()}
        assert db_genres == set(CANONICAL_GENRES)

    def test_book_genres_table_created(self, conn) -> None:
        """V3 migration creates the book_genres junction table."""
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='book_genres'"
        )
        assert cursor.fetchone() is not None

    def test_subjects_column_added_to_books(self, conn) -> None:
        """V3 migration adds a subjects column to the books table."""
        cursor = conn.execute("PRAGMA table_info(books)")
        columns = {row[1] for row in cursor.fetchall()}
        assert "subjects" in columns

    def test_schema_version_is_3(self, conn) -> None:
        """Schema version is 3 after migration."""
        cursor = conn.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        )
        assert cursor.fetchone()[0] == 3


class TestMappingSubjects:
    """Tests for subjects serialization in mapping functions."""

    def test_metadata_to_row_serializes_subjects(self) -> None:
        """metadata_to_row includes subjects as JSON string."""
        meta = BookMetadata(
            title="Test",
            subjects=["Fiction", "Mystery"],
            source_path=Path("/test.epub"),
        )
        row = metadata_to_row(meta, file_hash="abc123")
        assert row["subjects"] == json.dumps(["Fiction", "Mystery"])

    def test_metadata_to_row_empty_subjects(self) -> None:
        """Empty subjects serializes to JSON empty array."""
        meta = BookMetadata(title="Test", source_path=Path("/test.epub"))
        row = metadata_to_row(meta, file_hash="abc123")
        assert row["subjects"] == json.dumps([])

    def test_row_to_metadata_deserializes_subjects(self) -> None:
        """row_to_metadata restores subjects from JSON."""
        row = {
            "title": "Test",
            "authors": json.dumps(["Author"]),
            "author_sort": None,
            "language": "en",
            "publisher": None,
            "isbn": None,
            "description": None,
            "series": None,
            "series_index": None,
            "identifiers": json.dumps({}),
            "source_path": "/test.epub",
            "subjects": json.dumps(["Fiction", "Horror"]),
        }
        meta = row_to_metadata(row)
        assert meta.subjects == ["Fiction", "Horror"]

    def test_row_to_metadata_null_subjects(self) -> None:
        """NULL subjects in DB returns empty list."""
        row = {
            "title": "Test",
            "authors": json.dumps([]),
            "author_sort": None,
            "language": None,
            "publisher": None,
            "isbn": None,
            "description": None,
            "series": None,
            "series_index": None,
            "identifiers": json.dumps({}),
            "source_path": "/test.epub",
            "subjects": None,
        }
        meta = row_to_metadata(row)
        assert meta.subjects == []
