# ABOUTME: Integration tests for schema migration across database lifecycle.
# ABOUTME: Validates that V1 databases upgrade correctly and preserve data.

import sqlite3
from pathlib import Path

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import _get_schema_version, open_library
from bookery.db.schema import SCHEMA_V1
from bookery.metadata.types import BookMetadata


class TestMigrationLifecycle:
    """Integration tests for the migration pipeline."""

    def test_v1_db_with_books_migrates_and_supports_tags(self, tmp_path: Path) -> None:
        """A V1 database with existing books migrates to V2 and supports tagging."""
        db_path = tmp_path / "lifecycle.db"

        # Step 1: Create a V1 database with a book
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA_V1)
        conn.execute(
            "INSERT INTO books (title, authors, source_path, file_hash) "
            "VALUES ('Legacy Book', '[\"Old Author\"]', '/legacy.epub', 'legacy_hash')"
        )
        conn.commit()
        conn.close()

        # Step 2: Open with bookery to trigger migration
        conn = open_library(db_path)
        assert _get_schema_version(conn) == 2

        # Step 3: Verify the book survived and tags work
        catalog = LibraryCatalog(conn)
        records = catalog.list_all()
        assert len(records) == 1
        assert records[0].metadata.title == "Legacy Book"

        # Step 4: Tag the legacy book
        catalog.add_tag(records[0].id, "imported")
        tags = catalog.get_tags_for_book(records[0].id)
        assert tags == ["imported"]
        conn.close()

    def test_multiple_reopens_dont_break_schema(self, tmp_path: Path) -> None:
        """Opening the database multiple times is safe and idempotent."""
        db_path = tmp_path / "reopen.db"

        # Open 3 times
        for _ in range(3):
            conn = open_library(db_path)
            assert _get_schema_version(conn) == 2
            conn.close()

        # Final open — add a book and tag it
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)
        book_id = catalog.add_book(
            BookMetadata(title="Reopen Book", source_path=Path("/reopen.epub")),
            file_hash="reopen_hash",
        )
        catalog.add_tag(book_id, "stable")
        assert catalog.get_tags_for_book(book_id) == ["stable"]
        conn.close()

    def test_fts_still_works_after_migration(self, tmp_path: Path) -> None:
        """FTS5 search continues to work after V2 migration."""
        db_path = tmp_path / "fts.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)

        catalog.add_book(
            BookMetadata(
                title="Searchable Book",
                authors=["Author Name"],
                source_path=Path("/search.epub"),
            ),
            file_hash="search_hash",
        )

        results = catalog.search("Searchable")
        assert len(results) == 1
        assert results[0].metadata.title == "Searchable Book"
        conn.close()
