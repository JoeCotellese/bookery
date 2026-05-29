# ABOUTME: Unit tests for device shelf state methods in LibraryCatalog.
# ABOUTME: Validates upsert, get, and list operations for collection shelf sync state.

from pathlib import Path

import pytest

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


@pytest.fixture()
def catalog(tmp_path: Path) -> LibraryCatalog:
    """Provide a LibraryCatalog backed by a temporary database."""
    conn = open_library(tmp_path / "shelf_state_test.db")
    return LibraryCatalog(conn)


@pytest.fixture()
def device_id(catalog: LibraryCatalog) -> int:
    """Register a sample device and return its ID."""
    return catalog.upsert_device(
        kind="kobo",
        serial="SN123456789",
        label="My Kobo",
        now="2024-01-15T10:00:00",
    )


@pytest.fixture()
def collection_id(catalog: LibraryCatalog) -> int:
    """Create a sample collection and return its ID."""
    return catalog.create_collection("Favorites", "My favorite books")


@pytest.fixture()
def book_id(catalog: LibraryCatalog) -> int:
    """Add a sample book and return its ID."""
    return catalog.add_book(
        BookMetadata(title="Test Book", source_path=Path("/books/test.epub")),
        file_hash="test_hash",
    )


class TestDeviceShelfState:
    """Tests for device_shelf_state CRUD operations."""

    def test_upsert_device_shelf_state_creates_new(
        self,
        catalog: LibraryCatalog,
        device_id: int,
        collection_id: int,
    ) -> None:
        """Creating a new shelf state record works."""
        catalog.upsert_device_shelf_state(
            device_id=device_id,
            collection_id=collection_id,
            shelf_id="shelf-uuid-123",
            shelf_name="Favorites",
            last_pushed_at="2024-01-15T10:30:00",
            book_count_on_device=5,
        )

        state = catalog.get_collection_shelf_state(device_id, collection_id)
        assert state is not None
        assert state["shelf_id"] == "shelf-uuid-123"
        assert state["shelf_name"] == "Favorites"
        assert state["last_pushed_at"] == "2024-01-15T10:30:00"
        assert state["book_count_on_device"] == 5

    def test_upsert_updates_existing(
        self,
        catalog: LibraryCatalog,
        device_id: int,
        collection_id: int,
    ) -> None:
        """Upsert updates existing record."""
        catalog.upsert_device_shelf_state(
            device_id=device_id,
            collection_id=collection_id,
            shelf_id="shelf-uuid-123",
            shelf_name="Favorites",
            last_pushed_at="2024-01-15T10:30:00",
            book_count_on_device=5,
        )

        catalog.upsert_device_shelf_state(
            device_id=device_id,
            collection_id=collection_id,
            shelf_id="shelf-uuid-456",
            shelf_name="My Favorites",
            last_pushed_at="2024-01-15T11:00:00",
            book_count_on_device=3,
        )

        state = catalog.get_collection_shelf_state(device_id, collection_id)
        assert state is not None
        assert state["shelf_id"] == "shelf-uuid-456"
        assert state["shelf_name"] == "My Favorites"
        assert state["last_pushed_at"] == "2024-01-15T11:00:00"
        assert state["book_count_on_device"] == 3

    def test_get_collection_shelf_state_nonexistent_returns_none(
        self,
        catalog: LibraryCatalog,
        device_id: int,
        collection_id: int,
    ) -> None:
        """Getting non-existent state returns None."""
        state = catalog.get_collection_shelf_state(device_id, collection_id)
        assert state is None

    def test_delete_collection_shelf_state(
        self,
        catalog: LibraryCatalog,
        device_id: int,
        collection_id: int,
    ) -> None:
        """Deleting a shelf state record removes it."""
        catalog.upsert_device_shelf_state(
            device_id=device_id,
            collection_id=collection_id,
            shelf_id="shelf-uuid-123",
            shelf_name="Favorites",
            last_pushed_at="2024-01-15T10:30:00",
        )

        state = catalog.get_collection_shelf_state(device_id, collection_id)
        assert state is not None

        catalog.delete_collection_shelf_state(device_id, collection_id)

        state = catalog.get_collection_shelf_state(device_id, collection_id)
        assert state is None

    def test_list_collection_shelf_candidates_empty(
        self,
        catalog: LibraryCatalog,
        device_id: int,
    ) -> None:
        """No candidates when no books synced to device."""
        candidates = catalog.list_collection_shelf_candidates(device_id=device_id)
        assert candidates == []

    def test_list_collection_shelf_candidates_with_books(
        self,
        catalog: LibraryCatalog,
        device_id: int,
        collection_id: int,
        book_id: int,
    ) -> None:
        """Collections with synced books appear as candidates."""
        catalog.add_books_to_collection(collection_id, [book_id])

        catalog.upsert_device_file(
            device_id=device_id,
            book_id=book_id,
            remote_path="/mnt/onboard/Bookery/Test Book/Test Book.kepub.epub",
            now="2024-01-15T10:00:00",
        )

        candidates = catalog.list_collection_shelf_candidates(device_id=device_id)

        assert len(candidates) == 1
        cand = candidates[0]
        assert cand["collection_id"] == collection_id
        assert cand["name"] == "Favorites"
        assert cand["books_on_device"] == 1
        assert cand["books_in_collection"] == 1
        assert cand["shelf_id"] is None
        assert cand["last_pushed_at"] is None

    def test_list_collection_shelf_candidates_returns_existing_state(
        self,
        catalog: LibraryCatalog,
        device_id: int,
        collection_id: int,
        book_id: int,
    ) -> None:
        """Candidates include existing shelf state when present."""
        catalog.add_books_to_collection(collection_id, [book_id])

        catalog.upsert_device_file(
            device_id=device_id,
            book_id=book_id,
            remote_path="/mnt/onboard/Bookery/Test Book/Test Book.kepub.epub",
            now="2024-01-15T10:00:00",
        )

        catalog.upsert_device_shelf_state(
            device_id=device_id,
            collection_id=collection_id,
            shelf_id="shelf-uuid-123",
            shelf_name="Favorites",
            last_pushed_at="2024-01-15T10:30:00",
            book_count_on_device=1,
        )

        candidates = catalog.list_collection_shelf_candidates(device_id=device_id)

        assert len(candidates) == 1
        cand = candidates[0]
        assert cand["shelf_id"] == "shelf-uuid-123"
        assert cand["last_pushed_at"] == "2024-01-15T10:30:00"
