# ABOUTME: Regression coverage for author fix-sort metadata verification.
# ABOUTME: Exercises real EPUB read/write and catalog updates before atomic replacement.

from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from bookery.cli.commands.authors_cmd import _apply_fix, _find_candidates
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.db.hashing import compute_file_hash
from bookery.formats.epub import read_epub_metadata, write_epub_metadata
from bookery.metadata import BookMetadata


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        ("title", "Wrong Title"),
        ("authors", ["Wrong Author"]),
        ("language", "fr"),
        ("publisher", "Wrong Publisher"),
        ("description", "Wrong Description"),
        ("subjects", ["Wrong Subject"]),
        ("series", "Wrong Series"),
        ("series_index", 99.0),
    ],
)
def test_corrupted_metadata_never_replaces_library_epub(
    sample_epub: Path, tmp_path: Path, field: str, wrong_value: object
) -> None:
    original = sample_epub.read_bytes()
    original_hash = compute_file_hash(sample_epub)
    metadata = replace(
        read_epub_metadata(sample_epub), subjects=["Mystery"], series="A Series", series_index=2.0
    )

    def lossy_write(path: Path, expected: BookMetadata) -> None:
        write_epub_metadata(path, replace(expected, **{field: wrong_value}))

    with closing(open_library(tmp_path / "lib.db")) as conn:
        catalog = LibraryCatalog(conn)
        book_id = catalog.add_book(metadata, file_hash=original_hash, output_path=sample_epub)
        candidates, unreadable = _find_candidates(catalog)
        assert not unreadable and len(candidates) == 1
        with patch("bookery.cli.commands.authors_cmd.write_epub_metadata", lossy_write):
            failed = _apply_fix(catalog, candidates[0])

        assert sample_epub.read_bytes() == original
        assert failed == [field]
        assert not list(tmp_path.glob("*.fixtmp"))
        record = catalog.get_by_id(book_id)
        assert record is not None and record.file_hash == original_hash
