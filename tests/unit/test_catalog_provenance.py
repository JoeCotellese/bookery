# ABOUTME: Tests for the book_field_provenance schema and catalog API.
# ABOUTME: Covers add/update provenance, lock + respect_locked, and get_provenance.

from pathlib import Path

import pytest

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


@pytest.fixture
def catalog(tmp_path: Path):
    conn = open_library(tmp_path / "lib.db")
    try:
        yield LibraryCatalog(conn)
    finally:
        conn.close()


def _add(catalog: LibraryCatalog, **overrides) -> int:
    meta = BookMetadata(
        title=overrides.get("title", "Dune"),
        authors=overrides.get("authors", ["Frank Herbert"]),
        isbn=overrides.get("isbn", "9780441013593"),
        source_path=Path("/tmp/x.epub"),
    )
    return catalog.add_book(meta, file_hash=overrides.get("hash", "a" * 64))


def test_add_book_records_provenance_for_populated_fields(catalog) -> None:
    book_id = _add(catalog)
    prov = catalog.get_provenance(book_id)
    assert "title" in prov
    assert "authors" in prov
    assert "isbn" in prov
    assert all(e.source == "extracted" for e in prov.values())
    # None-valued fields aren't recorded.
    assert "publisher" not in prov


def test_add_book_accepts_custom_source(catalog) -> None:
    meta = BookMetadata(
        title="Dune",
        authors=["Frank Herbert"],
        source_path=Path("/tmp/x.epub"),
    )
    book_id = catalog.add_book(meta, file_hash="b" * 64, source="openlibrary")
    prov = catalog.get_provenance(book_id)
    assert prov["title"].source == "openlibrary"


def test_update_book_records_provenance_per_field(catalog) -> None:
    book_id = _add(catalog)
    written = catalog.update_book(
        book_id,
        source="googlebooks",
        page_count=412,
        description="A desert epic.",
    )
    assert set(written) == {"page_count", "description"}
    prov = catalog.get_provenance(book_id)
    assert prov["page_count"].source == "googlebooks"
    assert prov["description"].source == "googlebooks"
    # Original title provenance is unchanged.
    assert prov["title"].source == "extracted"


def test_update_book_per_field_provenance_override(catalog) -> None:
    book_id = _add(catalog)
    catalog.update_book(
        book_id,
        source="consensus",
        provenance={"page_count": "googlebooks"},
        page_count=412,
        description="Epic.",
    )
    prov = catalog.get_provenance(book_id)
    assert prov["page_count"].source == "googlebooks"
    assert prov["description"].source == "consensus"


def test_locked_field_is_not_overwritten_when_respected(catalog) -> None:
    book_id = _add(catalog)
    catalog.update_book(book_id, source="user", title="My Custom Title")
    catalog.set_field_lock(book_id, "title", True)

    written = catalog.update_book(
        book_id,
        source="openlibrary",
        respect_locked=True,
        title="Auto-Fetched Title",
        description="Also new.",
    )

    assert "title" not in written
    assert "description" in written

    record = catalog.get_by_id(book_id)
    assert record is not None
    assert record.metadata.title == "My Custom Title"


def test_unlock_allows_overwrite(catalog) -> None:
    book_id = _add(catalog)
    catalog.set_field_lock(book_id, "title", True)
    catalog.set_field_lock(book_id, "title", False)

    written = catalog.update_book(
        book_id,
        source="openlibrary",
        respect_locked=True,
        title="Auto-Fetched Title",
    )
    assert "title" in written
    record = catalog.get_by_id(book_id)
    assert record is not None
    assert record.metadata.title == "Auto-Fetched Title"


def test_set_field_lock_creates_user_row_when_none_exists(catalog) -> None:
    book_id = _add(catalog)
    catalog.set_field_lock(book_id, "never_set", True)
    prov = catalog.get_provenance(book_id)
    assert prov["never_set"].source == "user"
    assert prov["never_set"].locked is True


def test_get_locked_fields(catalog) -> None:
    book_id = _add(catalog)
    catalog.set_field_lock(book_id, "title", True)
    catalog.set_field_lock(book_id, "isbn", True)
    catalog.set_field_lock(book_id, "isbn", False)
    locked = catalog.get_locked_fields(book_id)
    assert locked == {"title"}


def test_update_book_without_source_leaves_provenance_unchanged(catalog) -> None:
    book_id = _add(catalog)
    before = catalog.get_provenance(book_id)["title"].source
    catalog.update_book(book_id, description="New desc.")
    after = catalog.get_provenance(book_id)["title"].source
    assert before == after
    assert "description" not in catalog.get_provenance(book_id)
