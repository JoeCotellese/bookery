# ABOUTME: Integration tests for collections workflow.
# ABOUTME: Tests cascade behavior and catalog interaction.

from pathlib import Path

import pytest

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


@pytest.fixture()
def catalog(tmp_path: Path) -> LibraryCatalog:
    """Provide a LibraryCatalog backed by a temporary database."""
    conn = open_library(tmp_path / "integration_test.db")
    return LibraryCatalog(conn)


class TestCollectionsIntegration:
    """Integration tests for collections functionality."""

    def test_collection_deletion_preserves_books(self, catalog: LibraryCatalog) -> None:
        """Deleting a collection does not delete the books in it."""
        # Create collection and add books
        collection_id = catalog.create_collection("To Delete")
        book_ids = [
            catalog.add_book(
                BookMetadata(title=f"Book {i}", source_path=Path(f"/books/{i}.epub")),
                file_hash=f"hash_{i}",
            )
            for i in range(3)
        ]
        catalog.add_books_to_collection(collection_id, book_ids)

        # Delete collection
        catalog.delete_collection(collection_id)

        # Verify books still exist
        for book_id in book_ids:
            book = catalog.get_by_id(book_id)
            assert book is not None

    def test_duplicate_book_add_is_idempotent(self, catalog: LibraryCatalog) -> None:
        """Adding the same book to a collection twice is idempotent."""
        collection_id = catalog.create_collection("Favorites")
        book_id = catalog.add_book(
            BookMetadata(title="Great Book", source_path=Path("/books/great.epub")),
            file_hash="hash",
        )

        # Add the same book multiple times
        catalog.add_books_to_collection(collection_id, [book_id])
        catalog.add_books_to_collection(collection_id, [book_id])
        catalog.add_books_to_collection(collection_id, [book_id])

        # Should only be in collection once
        books = catalog.get_collection_books(collection_id)
        assert len(books) == 1
        assert books[0].id == book_id

    def test_collection_books_ordered_by_title(self, catalog: LibraryCatalog) -> None:
        """Books in a collection are ordered by title_sort."""
        collection_id = catalog.create_collection("Favorites")

        # Add books in reverse alphabetical order
        book_z = catalog.add_book(
            BookMetadata(title="Zebra", source_path=Path("/books/z.epub")),
            file_hash="z_hash",
        )
        book_a = catalog.add_book(
            BookMetadata(title="Apple", source_path=Path("/books/a.epub")),
            file_hash="a_hash",
        )
        book_m = catalog.add_book(
            BookMetadata(title="Mango", source_path=Path("/books/m.epub")),
            file_hash="m_hash",
        )

        catalog.add_books_to_collection(collection_id, [book_z, book_a, book_m])

        books = catalog.get_collection_books(collection_id)
        titles = [b.metadata.title for b in books]
        assert titles == ["Apple", "Mango", "Zebra"]

    def test_collections_ordered_by_name(self, catalog: LibraryCatalog) -> None:
        """Collections are listed ordered by name."""
        # Create collections in reverse order
        catalog.create_collection("Zebra")
        catalog.create_collection("Apple")
        catalog.create_collection("Mango")

        collections = catalog.list_collections()
        names = [c["name"] for c in collections]
        assert names == ["Apple", "Mango", "Zebra"]

    def test_rename_updates_collection_name(self, catalog: LibraryCatalog) -> None:
        """Renaming a collection updates its name everywhere."""
        collection_id = catalog.create_collection("Old Name", "Description")
        book_id = catalog.add_book(
            BookMetadata(title="Book", source_path=Path("/books/b.epub")),
            file_hash="hash",
        )
        catalog.add_books_to_collection(collection_id, [book_id])

        # Rename
        catalog.rename_collection(collection_id, "New Name")

        # Verify by ID
        collection = catalog.get_collection_by_id(collection_id)
        assert collection is not None
        assert collection["name"] == "New Name"
        assert collection["description"] == "Description"

        # Verify by new name
        collection = catalog.get_collection_by_name("New Name")
        assert collection is not None
        assert collection["name"] == "New Name"

        # Old name should not exist
        collection = catalog.get_collection_by_name("Old Name")
        assert collection is None

    def test_collection_count_updates(self, catalog: LibraryCatalog) -> None:
        """Collection book count updates when books are added/removed."""
        collection_id = catalog.create_collection("Favorites")
        book_ids = [
            catalog.add_book(
                BookMetadata(title=f"Book {i}", source_path=Path(f"/books/{i}.epub")),
                file_hash=f"hash_{i}",
            )
            for i in range(5)
        ]

        # Add 3 books
        catalog.add_books_to_collection(collection_id, book_ids[:3])
        collections = catalog.list_collections()
        assert collections[0]["book_count"] == 3

        # Add 2 more
        catalog.add_books_to_collection(collection_id, book_ids[3:])
        collections = catalog.list_collections()
        assert collections[0]["book_count"] == 5

        # Remove 1
        catalog.remove_books_from_collection(collection_id, [book_ids[0]])
        collections = catalog.list_collections()
        assert collections[0]["book_count"] == 4

    def test_get_collections_for_book(self, catalog: LibraryCatalog) -> None:
        """Can query all collections a book belongs to."""
        # Create collections
        col1 = catalog.create_collection("Favorites")
        col2 = catalog.create_collection("To Read")
        col3 = catalog.create_collection("Not In This")

        # Add book
        book_id = catalog.add_book(
            BookMetadata(title="Book", source_path=Path("/books/b.epub")),
            file_hash="hash",
        )

        # Add to two collections
        catalog.add_books_to_collection(col1, [book_id])
        catalog.add_books_to_collection(col2, [book_id])

        # Query
        collections = catalog.get_collections_for_book(book_id)
        collection_ids = {c["id"] for c in collections}

        assert col1 in collection_ids
        assert col2 in collection_ids
        assert col3 not in collection_ids

    def test_empty_collection_operations(self, catalog: LibraryCatalog) -> None:
        """Operations on empty collections work correctly."""
        collection_id = catalog.create_collection("Empty")

        # List empty collection
        books = catalog.get_collection_books(collection_id)
        assert books == []

        # Remove from empty collection (should succeed)
        catalog.remove_books_from_collection(collection_id, [999])

        # Delete empty collection
        catalog.delete_collection(collection_id)

        # Verify deleted
        assert catalog.get_collection_by_id(collection_id) is None

    def test_case_insensitive_name_lookup(self, catalog: LibraryCatalog) -> None:
        """Collection names are case-insensitive for lookup."""
        catalog.create_collection("Favorites")

        # Should be able to find with different cases
        assert catalog.get_collection_by_name("favorites") is not None
        assert catalog.get_collection_by_name("FAVORITES") is not None
        assert catalog.get_collection_by_name("FaVoRiTeS") is not None
