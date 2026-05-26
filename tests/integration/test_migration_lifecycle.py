# ABOUTME: Integration tests for schema migration across database lifecycle.
# ABOUTME: Validates that V1 databases upgrade correctly and preserve data.

import sqlite3
from pathlib import Path

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import _get_schema_version, open_library
from bookery.db.schema import MIGRATIONS, SCHEMA_V1
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
        assert _get_schema_version(conn) == 9

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
            assert _get_schema_version(conn) == 9
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

    def test_v8_db_with_article_titles_backfills_title_sort(self, tmp_path: Path) -> None:
        """V9 backfill strips leading English articles for existing rows.

        Stage a database at V8 (the pre-#192 production schema), insert books
        whose titles begin with "The" / "A" / "An", then trigger the V9
        migration via ``open_library`` and assert the new ``title_sort`` column
        is backfilled per the article-stripping rule. Falls back to the raw
        title when stripping would leave an empty string.
        """
        db_path = tmp_path / "v9_backfill.db"

        # Step 1: hand-roll a V8 database — V1 plus every migration up to and
        # including V8. Stops short of V9 so we can verify its backfill.
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA_V1)
        for version, sql in MIGRATIONS:
            if version <= 8:
                conn.executescript(sql)
        # Step 2: insert rows directly so we bypass any Python-side population
        # of `title_sort` (the column doesn't exist yet at V8).
        rows = [
            ("The Hobbit", "Tolkien, J.R.R."),
            ("A Wizard of Earthsea", "Le Guin, Ursula K."),
            ("An American Tragedy", "Dreiser, Theodore"),
            ("Dune", "Herbert, Frank"),
            ("the lower case", "Author"),
            ("The", "Edge Case Author"),  # fallback: stripping → empty
        ]
        for i, (title, author) in enumerate(rows):
            conn.execute(
                "INSERT INTO books (title, authors, author_sort, source_path, file_hash) "
                "VALUES (?, ?, ?, ?, ?)",
                (title, f'["{author}"]', author, f"/{i}.epub", f"hash{i}"),
            )
        conn.commit()
        conn.close()

        # Step 3: open via the library code, which applies V9.
        conn = open_library(db_path)
        assert _get_schema_version(conn) == 9

        # Step 4: verify backfill on every row.
        cursor = conn.execute("SELECT title, title_sort FROM books ORDER BY id")
        backfilled = {row[0]: row[1] for row in cursor.fetchall()}
        assert backfilled == {
            "The Hobbit": "Hobbit",
            "A Wizard of Earthsea": "Wizard of Earthsea",
            "An American Tragedy": "American Tragedy",
            "Dune": "Dune",
            "the lower case": "lower case",
            "The": "The",  # fallback when stripping leaves empty
        }
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
