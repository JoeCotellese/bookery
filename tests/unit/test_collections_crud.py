# ABOUTME: Unit tests for collection CRUD operations on LibraryCatalog.
# ABOUTME: Validates create, add/remove books, list, and query methods for collections.

import sqlite3
from pathlib import Path

import pytest

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


@pytest.fixture()
def catalog(tmp_path: Path) -> LibraryCatalog:
    """Provide a LibraryCatalog backed by a temporary database."""
    conn = open_library(tmp_path / "collections_test.db")
    return LibraryCatalog(conn)


@pytest.fixture()
def book_id(catalog: LibraryCatalog) -> int:
    """Add a sample book and return its ID."""
    return catalog.add_book(
        BookMetadata(title="The Name of the Rose", source_path=Path("/books/rose.epub")),
        file_hash="rose_hash",
    )


@pytest.fixture()
def book_ids(catalog: LibraryCatalog) -> list[int]:
    """Add multiple sample books and return their IDs."""
    ids = []
    for i in range(3):
        book_id = catalog.add_book(
            BookMetadata(title=f"Book {i}", source_path=Path(f"/books/book{i}.epub")),
            file_hash=f"hash_{i}",
        )
        ids.append(book_id)
    return ids


class TestMigration:
    """Tests for V11 schema migration."""

    def test_migration_applies(self, tmp_path: Path) -> None:
        """V11 migration creates collections and collection_books tables."""
        conn = open_library(tmp_path / "migration_test.db")
        
        # Check collections table exists
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='collections'"
        )
        assert cursor.fetchone() is not None, "collections table should exist"
        
        # Check collection_books table exists
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='collection_books'"
        )
        assert cursor.fetchone() is not None, "collection_books table should exist"
        
        conn.close()

    def test_collections_name_has_nocase_collation(self, tmp_path: Path) -> None:
        """Collections name column uses NOCASE collation to prevent duplicates."""
        conn = open_library(tmp_path / "nocase_test.db")
        
        # Insert a collection
        conn.execute("INSERT INTO collections (name, description) VALUES ('Favorites', 'My favs')")
        
        # Attempting to insert same name with different case should fail
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO collections (name, description) VALUES ('favorites', 'Duplicate')"
            )
        
        conn.close()

    def test_collection_books_cascade_on_collection_delete(self, catalog: LibraryCatalog) -> None:
        """Deleting a collection cascades to remove collection_books associations."""
        # Create a collection and add books
        collection_id = catalog.create_collection("Test Collection")
        book_ids = [
            catalog.add_book(
                BookMetadata(title=f"Book {i}", source_path=Path(f"/books/{i}.epub")),
                file_hash=f"hash_{i}",
            )
            for i in range(2)
        ]
        catalog.add_books_to_collection(collection_id, book_ids)
        
        # Verify books are in collection
        books = catalog.get_collection_books(collection_id)
        assert len(books) == 2
        
        # Delete the collection
        catalog.delete_collection(collection_id)
        
        # Verify junction table entries are gone
        conn = catalog._conn
        cursor = conn.execute(
            "SELECT COUNT(*) FROM collection_books WHERE collection_id = ?",
            (collection_id,)
        )
        assert cursor.fetchone()[0] == 0

    def test_collection_books_cascade_on_book_delete(self, catalog: LibraryCatalog) -> None:
        """Deleting a book cascades to remove collection_books associations."""
        # Create a collection and add books
        collection_id = catalog.create_collection("Test Collection")
        book_ids = [
            catalog.add_book(
                BookMetadata(title=f"Book {i}", source_path=Path(f"/books/{i}.epub")),
                file_hash=f"hash_{i}",
            )
            for i in range(2)
        ]
        catalog.add_books_to_collection(collection_id, book_ids)
        
        # Delete one book
        catalog.delete_book(book_ids[0])
        
        # Verify that book is no longer in collection
        books = catalog.get_collection_books(collection_id)
        assert len(books) == 1
        assert books[0].id == book_ids[1]


class TestCreateCollection:
    """Tests for LibraryCatalog.create_collection()."""

    def test_create_collection(self, catalog: LibraryCatalog) -> None:
        """Creating a collection returns its ID."""
        collection_id = catalog.create_collection("Favorites", "My favorite books")
        assert isinstance(collection_id, int)
        assert collection_id > 0

    def test_create_collection_with_description(self, catalog: LibraryCatalog) -> None:
        """Creating a collection stores the description."""
        collection_id = catalog.create_collection("Favorites", "My favorite books")
        collection = catalog.get_collection_by_id(collection_id)
        assert collection is not None
        assert collection["name"] == "Favorites"
        assert collection["description"] == "My favorite books"

    def test_create_collection_without_description(self, catalog: LibraryCatalog) -> None:
        """Creating a collection without description stores NULL."""
        collection_id = catalog.create_collection("Favorites")
        collection = catalog.get_collection_by_id(collection_id)
        assert collection is not None
        assert collection["description"] is None

    def test_create_duplicate_name_raises(self, catalog: LibraryCatalog) -> None:
        """Creating a collection with duplicate name raises IntegrityError."""
        catalog.create_collection("Favorites")
        with pytest.raises(sqlite3.IntegrityError):
            catalog.create_collection("Favorites")

    def test_create_case_insensitive_duplicate_raises(self, catalog: LibraryCatalog) -> None:
        """Creating a collection with different case but same name raises."""
        catalog.create_collection("Favorites")
        with pytest.raises(sqlite3.IntegrityError):
            catalog.create_collection("favorites")


class TestGetCollection:
    """Tests for LibraryCatalog.get_collection_by_id() and get_collection_by_name()."""

    def test_get_collection_by_id(self, catalog: LibraryCatalog) -> None:
        """Retrieving by ID returns the collection."""
        collection_id = catalog.create_collection("Favorites", "My favorites")
        collection = catalog.get_collection_by_id(collection_id)
        assert collection is not None
        assert collection["id"] == collection_id
        assert collection["name"] == "Favorites"
        assert collection["description"] == "My favorites"

    def test_get_collection_by_id_nonexistent_returns_none(self, catalog: LibraryCatalog) -> None:
        """Retrieving non-existent ID returns None."""
        collection = catalog.get_collection_by_id(9999)
        assert collection is None

    def test_get_collection_by_name(self, catalog: LibraryCatalog) -> None:
        """Retrieving by name returns the collection."""
        collection_id = catalog.create_collection("Favorites", "My favorites")
        collection = catalog.get_collection_by_name("Favorites")
        assert collection is not None
        assert collection["id"] == collection_id
        assert collection["name"] == "Favorites"

    def test_get_collection_by_name_case_insensitive(self, catalog: LibraryCatalog) -> None:
        """Retrieving by name is case-insensitive."""
        collection_id = catalog.create_collection("Favorites")
        collection = catalog.get_collection_by_name("favorites")
        assert collection is not None
        assert collection["id"] == collection_id

    def test_get_collection_by_name_nonexistent_returns_none(
        self, catalog: LibraryCatalog
    ) -> None:
        """Retrieving non-existent name returns None."""
        collection = catalog.get_collection_by_name("nonexistent")
        assert collection is None


class TestAddBooksToCollection:
    """Tests for LibraryCatalog.add_books_to_collection()."""

    def test_add_single_book(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Adding a single book associates it with the collection."""
        collection_id = catalog.create_collection("Favorites")
        catalog.add_books_to_collection(collection_id, [book_id])
        
        books = catalog.get_collection_books(collection_id)
        assert len(books) == 1
        assert books[0].id == book_id

    def test_add_multiple_books(self, catalog: LibraryCatalog, book_ids: list[int]) -> None:
        """Adding multiple books associates all with the collection."""
        collection_id = catalog.create_collection("Favorites")
        catalog.add_books_to_collection(collection_id, book_ids)
        
        books = catalog.get_collection_books(collection_id)
        assert len(books) == len(book_ids)
        book_ids_in_collection = {b.id for b in books}
        assert book_ids_in_collection == set(book_ids)

    def test_add_book_to_multiple_collections(self, catalog: LibraryCatalog, book_id: int) -> None:
        """A book can be in multiple collections."""
        collection1_id = catalog.create_collection("Favorites")
        collection2_id = catalog.create_collection("To Read")
        
        catalog.add_books_to_collection(collection1_id, [book_id])
        catalog.add_books_to_collection(collection2_id, [book_id])
        
        books1 = catalog.get_collection_books(collection1_id)
        books2 = catalog.get_collection_books(collection2_id)
        assert len(books1) == 1
        assert len(books2) == 1
        assert books1[0].id == book_id
        assert books2[0].id == book_id

    def test_add_duplicate_book_idempotent(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Adding the same book twice is idempotent."""
        collection_id = catalog.create_collection("Favorites")
        catalog.add_books_to_collection(collection_id, [book_id])
        catalog.add_books_to_collection(collection_id, [book_id])
        
        books = catalog.get_collection_books(collection_id)
        assert len(books) == 1

    def test_add_invalid_book_raises(self, catalog: LibraryCatalog) -> None:
        """Adding a non-existent book raises ValueError."""
        collection_id = catalog.create_collection("Favorites")
        with pytest.raises(ValueError, match="not found"):
            catalog.add_books_to_collection(collection_id, [9999])

    def test_add_to_invalid_collection_raises(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Adding to a non-existent collection raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            catalog.add_books_to_collection(9999, [book_id])


class TestRemoveBooksFromCollection:
    """Tests for LibraryCatalog.remove_books_from_collection()."""

    def test_remove_single_book(self, catalog: LibraryCatalog, book_ids: list[int]) -> None:
        """Removing a single book disassociates it from the collection."""
        collection_id = catalog.create_collection("Favorites")
        catalog.add_books_to_collection(collection_id, book_ids)
        
        catalog.remove_books_from_collection(collection_id, [book_ids[0]])
        
        books = catalog.get_collection_books(collection_id)
        assert len(books) == len(book_ids) - 1
        remaining_ids = {b.id for b in books}
        assert book_ids[0] not in remaining_ids

    def test_remove_multiple_books(self, catalog: LibraryCatalog, book_ids: list[int]) -> None:
        """Removing multiple books disassociates all from the collection."""
        collection_id = catalog.create_collection("Favorites")
        catalog.add_books_to_collection(collection_id, book_ids)
        
        catalog.remove_books_from_collection(collection_id, book_ids[:2])
        
        books = catalog.get_collection_books(collection_id)
        assert len(books) == 1
        assert books[0].id == book_ids[2]

    def test_remove_nonexistent_book_succeeds(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Removing a book not in the collection succeeds silently."""
        collection_id = catalog.create_collection("Favorites")
        catalog.add_books_to_collection(collection_id, [book_id])
        
        # Try to remove a book that was never added
        catalog.remove_books_from_collection(collection_id, [9999])
        
        # Original book should still be there
        books = catalog.get_collection_books(collection_id)
        assert len(books) == 1

    def test_remove_from_invalid_collection_raises(
        self, catalog: LibraryCatalog, book_id: int
    ) -> None:
        """Removing from a non-existent collection raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            catalog.remove_books_from_collection(9999, [book_id])


class TestListCollections:
    """Tests for LibraryCatalog.list_collections()."""

    def test_empty_library_no_collections(self, catalog: LibraryCatalog) -> None:
        """An empty library returns no collections."""
        collections = catalog.list_collections()
        assert collections == []

    def test_list_collections_with_counts(
        self, catalog: LibraryCatalog, book_ids: list[int]
    ) -> None:
        """list_collections returns collection info with book counts."""
        collection1_id = catalog.create_collection("Favorites")
        collection2_id = catalog.create_collection("To Read")
        
        catalog.add_books_to_collection(collection1_id, book_ids[:2])
        catalog.add_books_to_collection(collection2_id, book_ids[1:])
        
        collections = catalog.list_collections()
        
        # Should return 2 collections
        assert len(collections) == 2
        
        # Find collections by name
        by_name = {c["name"]: c for c in collections}
        
        assert "Favorites" in by_name
        assert by_name["Favorites"]["book_count"] == 2
        
        assert "To Read" in by_name
        assert by_name["To Read"]["book_count"] == 2

    def test_list_collections_ordered_by_name(self, catalog: LibraryCatalog) -> None:
        """Collections are returned ordered by name."""
        catalog.create_collection("Z Collection")
        catalog.create_collection("A Collection")
        catalog.create_collection("M Collection")
        
        collections = catalog.list_collections()
        names = [c["name"] for c in collections]
        assert names == ["A Collection", "M Collection", "Z Collection"]


class TestGetCollectionBooks:
    """Tests for LibraryCatalog.get_collection_books()."""

    def test_get_collection_books_ordered(self, catalog: LibraryCatalog) -> None:
        """Books are returned ordered by title_sort."""
        collection_id = catalog.create_collection("Favorites")
        
        # Add books with titles that sort differently
        book_z = catalog.add_book(
            BookMetadata(title="Zebra", source_path=Path("/books/z.epub")),
            file_hash="hash_z",
        )
        book_a = catalog.add_book(
            BookMetadata(title="Apple", source_path=Path("/books/a.epub")),
            file_hash="hash_a",
        )
        book_m = catalog.add_book(
            BookMetadata(title="Mango", source_path=Path("/books/m.epub")),
            file_hash="hash_m",
        )
        
        catalog.add_books_to_collection(collection_id, [book_z, book_a, book_m])
        
        books = catalog.get_collection_books(collection_id)
        titles = [b.metadata.title for b in books]
        assert titles == ["Apple", "Mango", "Zebra"]

    def test_get_collection_books_empty(self, catalog: LibraryCatalog) -> None:
        """Empty collection returns empty list."""
        collection_id = catalog.create_collection("Empty Collection")
        books = catalog.get_collection_books(collection_id)
        assert books == []

    def test_get_collection_books_invalid_collection(self, catalog: LibraryCatalog) -> None:
        """Getting books for non-existent collection raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            catalog.get_collection_books(9999)


class TestDeleteCollection:
    """Tests for LibraryCatalog.delete_collection()."""

    def test_delete_collection(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Deleting a collection removes it."""
        collection_id = catalog.create_collection("To Delete")
        catalog.add_books_to_collection(collection_id, [book_id])
        
        catalog.delete_collection(collection_id)
        
        collection = catalog.get_collection_by_id(collection_id)
        assert collection is None

    def test_delete_collection_nonexistent_raises(self, catalog: LibraryCatalog) -> None:
        """Deleting a non-existent collection raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            catalog.delete_collection(9999)


class TestRenameCollection:
    """Tests for LibraryCatalog.rename_collection()."""

    def test_rename_collection(self, catalog: LibraryCatalog) -> None:
        """Renaming a collection updates its name."""
        collection_id = catalog.create_collection("Old Name")
        
        catalog.rename_collection(collection_id, "New Name")
        
        collection = catalog.get_collection_by_id(collection_id)
        assert collection is not None
        assert collection["name"] == "New Name"

    def test_rename_collection_preserves_description(self, catalog: LibraryCatalog) -> None:
        """Renaming preserves other fields."""
        collection_id = catalog.create_collection("Old Name", "A description")
        
        catalog.rename_collection(collection_id, "New Name")
        
        collection = catalog.get_collection_by_id(collection_id)
        assert collection is not None
        assert collection["name"] == "New Name"
        assert collection["description"] == "A description"

    def test_rename_to_duplicate_raises(self, catalog: LibraryCatalog) -> None:
        """Renaming to an existing name raises IntegrityError."""
        catalog.create_collection("First")
        collection_id = catalog.create_collection("Second")
        
        with pytest.raises(sqlite3.IntegrityError):
            catalog.rename_collection(collection_id, "First")

    def test_rename_nonexistent_raises(self, catalog: LibraryCatalog) -> None:
        """Renaming a non-existent collection raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            catalog.rename_collection(9999, "New Name")


class TestGetCollectionsForBook:
    """Tests for LibraryCatalog.get_collections_for_book()."""

    def test_get_collections_for_book(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Returns all collections a book belongs to."""
        collection1_id = catalog.create_collection("Favorites")
        collection2_id = catalog.create_collection("To Read")
        collection3_id = catalog.create_collection("Not In This")
        
        catalog.add_books_to_collection(collection1_id, [book_id])
        catalog.add_books_to_collection(collection2_id, [book_id])
        
        collections = catalog.get_collections_for_book(book_id)
        collection_ids = {c["id"] for c in collections}
        
        assert collection1_id in collection_ids
        assert collection2_id in collection_ids
        assert collection3_id not in collection_ids

    def test_get_collections_ordered_by_name(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Collections are returned ordered by name."""
        collection_z = catalog.create_collection("Z Collection")
        collection_a = catalog.create_collection("A Collection")
        
        catalog.add_books_to_collection(collection_z, [book_id])
        catalog.add_books_to_collection(collection_a, [book_id])
        
        collections = catalog.get_collections_for_book(book_id)
        names = [c["name"] for c in collections]
        assert names == ["A Collection", "Z Collection"]

    def test_get_collections_empty(self, catalog: LibraryCatalog, book_id: int) -> None:
        """Book with no collections returns empty list."""
        collections = catalog.get_collections_for_book(book_id)
        assert collections == []
