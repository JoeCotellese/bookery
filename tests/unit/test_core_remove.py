# ABOUTME: Unit tests for the pure remove_book core logic.
# ABOUTME: Covers cascade, missing file, --keep-file, duplicate clusters, and empty-dir cleanup.

from pathlib import Path

import pytest

from bookery.core.remove import RemoveResult, remove_book
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


@pytest.fixture()
def catalog(tmp_path: Path) -> LibraryCatalog:
    """LibraryCatalog backed by a temporary SQLite database."""
    conn = open_library(tmp_path / "test.db")
    return LibraryCatalog(conn)


def _make_metadata(title: str = "The Name of the Rose") -> BookMetadata:
    return BookMetadata(
        title=title,
        authors=["Umberto Eco"],
        author_sort="Eco, Umberto",
        language="eng",
        publisher="Harcourt",
        isbn="9780156001311",
        source_path=Path("/books/source.epub"),
    )


def _write_epub(library_root: Path, relative: str = "Umberto Eco/Rose/book.epub") -> Path:
    path = library_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake epub bytes")
    return path


class TestRemoveBookHappyPath:
    def test_removes_db_row_and_file(self, catalog: LibraryCatalog, tmp_path: Path) -> None:
        output = _write_epub(tmp_path)
        book_id = catalog.add_book(_make_metadata(), file_hash="h1", output_path=output)

        result = remove_book(catalog, book_id, keep_file=False)

        assert isinstance(result, RemoveResult)
        assert result.book_id == book_id
        assert result.title == "The Name of the Rose"
        assert result.author == "Umberto Eco"
        assert result.file_path == output
        assert result.file_removed is True
        assert result.siblings_removed == ()
        assert result.warnings == ()
        assert catalog.get_by_id(book_id) is None
        assert not output.exists()

    def test_removes_sibling_kepub(self, catalog: LibraryCatalog, tmp_path: Path) -> None:
        output = _write_epub(tmp_path)
        sibling = output.with_name("book.kepub.epub")
        sibling.write_bytes(b"fake kepub")
        book_id = catalog.add_book(_make_metadata(), file_hash="h1", output_path=output)

        result = remove_book(catalog, book_id, keep_file=False)

        assert result.file_removed is True
        assert sibling in result.siblings_removed
        assert not sibling.exists()
        assert not output.exists()

    def test_empty_parent_dirs_cleaned_up(self, catalog: LibraryCatalog, tmp_path: Path) -> None:
        output = _write_epub(tmp_path, "Umberto Eco/Rose/book.epub")
        book_id = catalog.add_book(_make_metadata(), file_hash="h1", output_path=output)

        remove_book(catalog, book_id, keep_file=False)

        # Title directory and author directory should both be gone.
        assert not output.parent.exists()
        assert not output.parent.parent.exists()
        # library_root itself stays.
        assert tmp_path.exists()

    def test_parent_with_other_files_preserved(
        self, catalog: LibraryCatalog, tmp_path: Path
    ) -> None:
        output = _write_epub(tmp_path, "Umberto Eco/Rose/book.epub")
        # Drop a stranger file into the title directory.
        stranger = output.parent / "other.txt"
        stranger.write_text("keep me")
        book_id = catalog.add_book(_make_metadata(), file_hash="h1", output_path=output)

        remove_book(catalog, book_id, keep_file=False)

        assert output.parent.exists()
        assert stranger.exists()


class TestRemoveBookCascade:
    def test_cascade_removes_tags(self, catalog: LibraryCatalog, tmp_path: Path) -> None:
        output = _write_epub(tmp_path)
        book_id = catalog.add_book(_make_metadata(), file_hash="h1", output_path=output)
        catalog.add_tag(book_id, "favorite")

        remove_book(catalog, book_id, keep_file=False)

        # Tag itself stays in the tags table (orphan tags allowed), but the
        # link row must be gone. Easiest cross-check: re-query for tags on a
        # ghost book yields an empty list.
        assert catalog.get_tags_for_book(book_id) == []

    def test_cascade_removes_genres(self, catalog: LibraryCatalog, tmp_path: Path) -> None:
        output = _write_epub(tmp_path)
        book_id = catalog.add_book(_make_metadata(), file_hash="h1", output_path=output)
        catalog.add_genre(book_id, "Mystery & Thriller", is_primary=True)

        remove_book(catalog, book_id, keep_file=False)

        assert catalog.get_genres_for_book(book_id) == []


class TestRemoveBookMissingFile:
    def test_missing_file_emits_warning(self, catalog: LibraryCatalog, tmp_path: Path) -> None:
        output = _write_epub(tmp_path)
        book_id = catalog.add_book(_make_metadata(), file_hash="h1", output_path=output)
        output.unlink()

        result = remove_book(catalog, book_id, keep_file=False)

        assert result.file_removed is False
        assert any("already missing" in w for w in result.warnings)
        assert catalog.get_by_id(book_id) is None

    def test_no_output_path_still_removes_db_row(
        self, catalog: LibraryCatalog, tmp_path: Path
    ) -> None:
        book_id = catalog.add_book(_make_metadata(), file_hash="h1", output_path=None)

        result = remove_book(catalog, book_id, keep_file=False)

        assert result.file_path is None
        assert result.file_removed is False
        assert catalog.get_by_id(book_id) is None


class TestKeepFile:
    def test_keep_file_preserves_file(self, catalog: LibraryCatalog, tmp_path: Path) -> None:
        output = _write_epub(tmp_path)
        sibling = output.with_name("book.kepub.epub")
        sibling.write_bytes(b"fake kepub")
        book_id = catalog.add_book(_make_metadata(), file_hash="h1", output_path=output)

        result = remove_book(catalog, book_id, keep_file=True)

        assert result.file_removed is False
        assert result.siblings_removed == ()
        assert output.exists()
        assert sibling.exists()
        assert catalog.get_by_id(book_id) is None


class TestDuplicateCluster:
    def test_duplicate_cluster_preserves_file(
        self, catalog: LibraryCatalog, tmp_path: Path
    ) -> None:
        output = _write_epub(tmp_path)
        first_id = catalog.add_book(_make_metadata("Rose A"), file_hash="h1", output_path=output)
        second_id = catalog.add_book(_make_metadata("Rose B"), file_hash="h2", output_path=output)

        result = remove_book(catalog, first_id, keep_file=False)

        assert result.file_removed is False
        assert any("other catalog entries" in w for w in result.warnings)
        assert output.exists()
        # The other row is still pointing at it.
        assert catalog.get_by_id(second_id) is not None


class TestUnknownId:
    def test_unknown_id_raises(self, catalog: LibraryCatalog) -> None:
        with pytest.raises(ValueError, match="not found"):
            remove_book(catalog, 9999, keep_file=False)
