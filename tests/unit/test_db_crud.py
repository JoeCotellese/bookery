# ABOUTME: Unit tests for LibraryCatalog CRUD operations.
# ABOUTME: Validates add, get, update, delete, list, and duplicate detection.

from pathlib import Path

import pytest

from bookery.db.catalog import DuplicateBookError, LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


@pytest.fixture()
def catalog(tmp_path: Path) -> LibraryCatalog:
    """Provide a LibraryCatalog backed by a temporary database."""
    conn = open_library(tmp_path / "test.db")
    return LibraryCatalog(conn)


@pytest.fixture()
def sample_metadata() -> BookMetadata:
    """A fully-populated BookMetadata for testing."""
    return BookMetadata(
        title="The Name of the Rose",
        authors=["Umberto Eco"],
        author_sort="Eco, Umberto",
        language="eng",
        publisher="Harcourt",
        isbn="9780156001311",
        description="A mystery in a medieval monastery.",
        series="Adso of Melk",
        series_index=1.0,
        identifiers={"openlibrary_work": "OL123W"},
        source_path=Path("/books/rose.epub"),
    )


class TestAddBook:
    """Tests for LibraryCatalog.add_book."""

    def test_returns_integer_id(
        self, catalog: LibraryCatalog, sample_metadata: BookMetadata
    ) -> None:
        """add_book returns an integer row ID."""
        book_id = catalog.add_book(sample_metadata, file_hash="hash1")
        assert isinstance(book_id, int)
        assert book_id > 0

    def test_roundtrip_get_by_id(
        self, catalog: LibraryCatalog, sample_metadata: BookMetadata
    ) -> None:
        """Added book can be retrieved by ID with matching metadata."""
        book_id = catalog.add_book(sample_metadata, file_hash="hash1")
        record = catalog.get_by_id(book_id)

        assert record is not None
        assert record.metadata.title == "The Name of the Rose"
        assert record.metadata.authors == ["Umberto Eco"]
        assert record.metadata.isbn == "9780156001311"
        assert record.file_hash == "hash1"

    def test_duplicate_hash_raises(
        self, catalog: LibraryCatalog, sample_metadata: BookMetadata
    ) -> None:
        """Inserting the same file_hash twice raises DuplicateBookError."""
        catalog.add_book(sample_metadata, file_hash="hash1")
        with pytest.raises(DuplicateBookError):
            catalog.add_book(sample_metadata, file_hash="hash1")

    def test_add_with_output_path(
        self, catalog: LibraryCatalog, sample_metadata: BookMetadata
    ) -> None:
        """Output path is stored when provided."""
        book_id = catalog.add_book(
            sample_metadata, file_hash="hash1",
            output_path=Path("/output/rose.epub"),
        )
        record = catalog.get_by_id(book_id)
        assert record is not None
        assert record.output_path == Path("/output/rose.epub")


class TestGetBy:
    """Tests for get_by_id, get_by_hash, get_by_isbn."""

    def test_get_by_id_not_found(self, catalog: LibraryCatalog) -> None:
        """Returns None for nonexistent ID."""
        assert catalog.get_by_id(999) is None

    def test_get_by_hash(
        self, catalog: LibraryCatalog, sample_metadata: BookMetadata
    ) -> None:
        """Look up a book by its file hash."""
        catalog.add_book(sample_metadata, file_hash="unique_hash")
        record = catalog.get_by_hash("unique_hash")
        assert record is not None
        assert record.metadata.title == "The Name of the Rose"

    def test_get_by_hash_not_found(self, catalog: LibraryCatalog) -> None:
        """Returns None for unknown hash."""
        assert catalog.get_by_hash("nonexistent") is None

    def test_get_by_isbn(
        self, catalog: LibraryCatalog, sample_metadata: BookMetadata
    ) -> None:
        """Look up a book by ISBN."""
        catalog.add_book(sample_metadata, file_hash="hash1")
        record = catalog.get_by_isbn("9780156001311")
        assert record is not None
        assert record.metadata.title == "The Name of the Rose"

    def test_get_by_isbn_not_found(self, catalog: LibraryCatalog) -> None:
        """Returns None for unknown ISBN."""
        assert catalog.get_by_isbn("0000000000") is None


class TestListBooks:
    """Tests for list_all and list_by_series."""

    def test_list_all_returns_all(self, catalog: LibraryCatalog) -> None:
        """list_all returns all stored books."""
        catalog.add_book(
            BookMetadata(title="Book A", source_path=Path("/a.epub")),
            file_hash="hash_a",
        )
        catalog.add_book(
            BookMetadata(title="Book B", source_path=Path("/b.epub")),
            file_hash="hash_b",
        )
        catalog.add_book(
            BookMetadata(title="Book C", source_path=Path("/c.epub")),
            file_hash="hash_c",
        )
        results = catalog.list_all()
        assert len(results) == 3

    def test_list_all_empty_db(self, catalog: LibraryCatalog) -> None:
        """list_all returns empty list on empty database."""
        assert catalog.list_all() == []

    def test_list_by_series(self, catalog: LibraryCatalog) -> None:
        """Filter books by series name."""
        catalog.add_book(
            BookMetadata(
                title="Book 1", series="Cotton Malone", series_index=1.0,
                source_path=Path("/b1.epub"),
            ),
            file_hash="h1",
        )
        catalog.add_book(
            BookMetadata(
                title="Book 2", series="Cotton Malone", series_index=2.0,
                source_path=Path("/b2.epub"),
            ),
            file_hash="h2",
        )
        catalog.add_book(
            BookMetadata(
                title="Other Book", series="Other Series",
                source_path=Path("/other.epub"),
            ),
            file_hash="h3",
        )

        results = catalog.list_by_series("Cotton Malone")
        assert len(results) == 2
        assert results[0].metadata.series_index == 1.0
        assert results[1].metadata.series_index == 2.0


class TestUpdateBook:
    """Tests for update_book and set_output_path."""

    def test_update_changes_fields(
        self, catalog: LibraryCatalog, sample_metadata: BookMetadata
    ) -> None:
        """Updating title and authors reflects in subsequent get."""
        book_id = catalog.add_book(sample_metadata, file_hash="hash1")
        catalog.update_book(book_id, title="Il Nome della Rosa", authors=["Eco, Umberto"])

        record = catalog.get_by_id(book_id)
        assert record is not None
        assert record.metadata.title == "Il Nome della Rosa"
        assert record.metadata.authors == ["Eco, Umberto"]

    def test_update_sets_date_modified(
        self, catalog: LibraryCatalog, sample_metadata: BookMetadata
    ) -> None:
        """date_modified changes after an update."""
        book_id = catalog.add_book(sample_metadata, file_hash="hash1")
        record_before = catalog.get_by_id(book_id)
        assert record_before is not None

        catalog.update_book(book_id, title="Updated Title")
        record_after = catalog.get_by_id(book_id)
        assert record_after is not None
        assert record_after.date_modified >= record_before.date_modified

    def test_update_nonexistent_raises(self, catalog: LibraryCatalog) -> None:
        """Updating a nonexistent ID raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            catalog.update_book(999, title="Nope")

    def test_set_output_path(
        self, catalog: LibraryCatalog, sample_metadata: BookMetadata
    ) -> None:
        """set_output_path updates just the output_path column."""
        book_id = catalog.add_book(sample_metadata, file_hash="hash1")
        catalog.set_output_path(book_id, Path("/output/rose.epub"))

        record = catalog.get_by_id(book_id)
        assert record is not None
        assert record.output_path == Path("/output/rose.epub")


class TestDeleteBook:
    """Tests for delete_book."""

    def test_delete_removes_book(
        self, catalog: LibraryCatalog, sample_metadata: BookMetadata
    ) -> None:
        """Deleted book is no longer retrievable."""
        book_id = catalog.add_book(sample_metadata, file_hash="hash1")
        catalog.delete_book(book_id)
        assert catalog.get_by_id(book_id) is None

    def test_delete_nonexistent_raises(self, catalog: LibraryCatalog) -> None:
        """Deleting a nonexistent ID raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            catalog.delete_book(999)
