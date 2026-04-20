# ABOUTME: Verifies that LibraryCatalog writes canonicalize ISBN to ISBN-13.
# ABOUTME: Covers both insert (add_book) and update (update_book) paths.

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


def test_add_book_canonicalizes_isbn10_to_13(catalog):
    meta = BookMetadata(
        title="X", authors=["Y"], isbn="0151446474", source_path=Path("/tmp/x.epub"),
    )
    book_id = catalog.add_book(meta, file_hash="h" * 64)
    record = catalog.get_by_id(book_id)
    assert record is not None
    assert record.metadata.isbn == "9780151446476"


def test_add_book_keeps_hyphens_out(catalog):
    meta = BookMetadata(
        title="X", authors=["Y"], isbn="0-15-144647-4", source_path=Path("/tmp/x.epub"),
    )
    book_id = catalog.add_book(meta, file_hash="h" * 64)
    record = catalog.get_by_id(book_id)
    assert record is not None
    assert record.metadata.isbn == "9780151446476"


def test_update_book_canonicalizes_isbn(catalog):
    meta = BookMetadata(
        title="X", authors=["Y"], isbn=None, source_path=Path("/tmp/x.epub"),
    )
    book_id = catalog.add_book(meta, file_hash="h" * 64)

    catalog.update_book(book_id, isbn="0151446474")

    record = catalog.get_by_id(book_id)
    assert record is not None
    assert record.metadata.isbn == "9780151446476"
