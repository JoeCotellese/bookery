# ABOUTME: Unit tests for kobo_writer.py ContentList shelf operations.
# ABOUTME: Validates write_collection_shelves functionality.

import json
import sqlite3
from pathlib import Path

import pytest

from bookery.device.kobo_writer import (
    CollectionShelfUpdate,
    write_collection_shelves,
)


def create_kobo_db(db_path: Path) -> sqlite3.Connection:
    """Create a minimal Kobo database schema for testing."""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ContentType (
            ContentTypeID INTEGER PRIMARY KEY,
            Name TEXT NOT NULL
        );
        INSERT INTO ContentType (Name) VALUES ('eBook');
        
        CREATE TABLE IF NOT EXISTS Content (
            ContentID TEXT PRIMARY KEY,
            ContentType INTEGER REFERENCES ContentType(ContentTypeID),
            Title TEXT,
            Attribution TEXT
        );
        
        CREATE TABLE IF NOT EXISTS ContentList (
            ContentListID TEXT PRIMARY KEY,
            ListName TEXT,
            ListType TEXT,
            ContentIDList TEXT,
            ___UserID TEXT,
            ___SyncTime TEXT,
            DateCreated TEXT,
            DateModified TEXT
        );
    """)
    conn.commit()
    return conn


@pytest.fixture()
def kobo_db_path(tmp_path: Path) -> Path:
    """Provide a path to a temporary Kobo-style database."""
    db_path = tmp_path / "KoboReader.sqlite"
    conn = create_kobo_db(db_path)
    conn.execute(
        "INSERT INTO Content (ContentID, ContentType, Title) VALUES (?, ?, ?)",
        ("file:///mnt/onboard/Bookery/Author/Book1/Book1.kepub.epub", 1, "Book 1")
    )
    conn.execute(
        "INSERT INTO Content (ContentID, ContentType, Title) VALUES (?, ?, ?)",
        ("file:///mnt/onboard/Bookery/Author/Book2/Book2.kepub.epub", 1, "Book 2")
    )
    conn.commit()
    conn.close()
    return db_path


class TestWriteCollectionShelves:
    """Tests for write_collection_shelves function."""

    def test_write_single_shelf(self, kobo_db_path: Path) -> None:
        """Writing a single shelf creates the record."""
        updates = [
            CollectionShelfUpdate(
                shelf_id="shelf-uuid-1",
                shelf_name="Favorites",
                content_ids=["file:///mnt/onboard/Bookery/Author/Book1/Book1.kepub.epub"],
            )
        ]

        report = write_collection_shelves(
            db_path=kobo_db_path,
            updates=updates,
            now=lambda: "2024-01-15T10:30:00",
        )

        assert report.pushed_count == 1
        assert report.failed == []

        conn = sqlite3.connect(kobo_db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM ContentList WHERE ContentListID = ?",
            ("shelf-uuid-1",)
        ).fetchone()
        conn.close()

        assert row is not None
        assert row["ListName"] == "Favorites"
        assert row["ListType"] == "UserShelf"
        content_ids = json.loads(row["ContentIDList"])
        assert content_ids == ["file:///mnt/onboard/Bookery/Author/Book1/Book1.kepub.epub"]

    def test_write_multiple_shelves(self, kobo_db_path: Path) -> None:
        """Writing multiple shelves creates all records."""
        updates = [
            CollectionShelfUpdate(
                shelf_id="shelf-uuid-1",
                shelf_name="Favorites",
                content_ids=["file:///mnt/onboard/Bookery/Author/Book1/Book1.kepub.epub"],
            ),
            CollectionShelfUpdate(
                shelf_id="shelf-uuid-2",
                shelf_name="To Read",
                content_ids=["file:///mnt/onboard/Bookery/Author/Book2/Book2.kepub.epub"],
            ),
        ]

        report = write_collection_shelves(
            db_path=kobo_db_path,
            updates=updates,
            now=lambda: "2024-01-15T10:30:00",
        )

        assert report.pushed_count == 2

        conn = sqlite3.connect(kobo_db_path)
        cursor = conn.execute("SELECT COUNT(*) FROM ContentList WHERE ListType = 'UserShelf'")
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 2

    def test_write_shelf_updates_existing(self, kobo_db_path: Path) -> None:
        """Writing a shelf with existing ID updates it."""
        updates1 = [
            CollectionShelfUpdate(
                shelf_id="shelf-uuid-1",
                shelf_name="Favorites",
                content_ids=["file:///mnt/onboard/Bookery/Author/Book1/Book1.kepub.epub"],
            )
        ]
        write_collection_shelves(
            db_path=kobo_db_path,
            updates=updates1,
            now=lambda: "2024-01-15T10:30:00",
        )

        updates2 = [
            CollectionShelfUpdate(
                shelf_id="shelf-uuid-1",
                shelf_name="My Favorites",
                content_ids=[
                    "file:///mnt/onboard/Bookery/Author/Book1/Book1.kepub.epub",
                    "file:///mnt/onboard/Bookery/Author/Book2/Book2.kepub.epub",
                ],
            )
        ]
        report = write_collection_shelves(
            db_path=kobo_db_path,
            updates=updates2,
            now=lambda: "2024-01-15T11:00:00",
        )

        assert report.pushed_count == 1

        conn = sqlite3.connect(kobo_db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM ContentList WHERE ContentListID = ?",
            ("shelf-uuid-1",)
        ).fetchone()
        conn.close()

        assert row["ListName"] == "My Favorites"
        content_ids = json.loads(row["ContentIDList"])
        assert len(content_ids) == 2

    def test_write_empty_updates_list(self, kobo_db_path: Path) -> None:
        """Writing empty updates list returns empty report."""
        report = write_collection_shelves(
            db_path=kobo_db_path,
            updates=[],
            now=lambda: "2024-01-15T10:30:00",
        )

        assert report.pushed_count == 0
        assert report.failed == []

    def test_write_shelf_with_many_content_ids(self, kobo_db_path: Path) -> None:
        """Shelf with many content IDs stores them as JSON list."""
        content_ids = [
            f"file:///mnt/onboard/Bookery/Book{i}.kepub.epub"
            for i in range(100)
        ]

        updates = [
            CollectionShelfUpdate(
                shelf_id="shelf-uuid-big",
                shelf_name="Big Collection",
                content_ids=content_ids,
            )
        ]

        report = write_collection_shelves(
            db_path=kobo_db_path,
            updates=updates,
            now=lambda: "2024-01-15T10:30:00",
        )

        assert report.pushed_count == 1

        conn = sqlite3.connect(kobo_db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT ContentIDList FROM ContentList WHERE ContentListID = ?",
            ("shelf-uuid-big",)
        ).fetchone()
        conn.close()

        stored = json.loads(row["ContentIDList"])
        assert len(stored) == 100
        assert stored[0] == "file:///mnt/onboard/Bookery/Book0.kepub.epub"
