# ABOUTME: Atomic replacement failure tests for author fix-sort.
# ABOUTME: Ensures a failed swap preserves the original and never updates its hash.

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from bookery.cli.commands.authors_cmd import _apply_fix, _Candidate
from bookery.db.catalog import LibraryCatalog
from bookery.db.mapping import BookRecord
from bookery.formats.epub import read_epub_metadata


def test_replace_failure_keeps_original_and_hash(sample_epub: Path, tmp_path: Path) -> None:
    original = sample_epub.read_bytes()
    metadata = read_epub_metadata(sample_epub)
    record = BookRecord(1, metadata, "old-hash", sample_epub, sample_epub, "", "")
    catalog = Mock(spec=LibraryCatalog)
    candidate = _Candidate(record, [], [])
    with (
        patch("bookery.cli.commands.authors_cmd.write_epub_metadata"),
        patch("bookery.cli.commands.authors_cmd.os.replace", side_effect=OSError("swap failed")),
        pytest.raises(OSError, match="swap failed"),
    ):
        _apply_fix(catalog, candidate)

    assert sample_epub.read_bytes() == original
    assert not list(tmp_path.glob("*.fixtmp"))
    catalog.update_book.assert_not_called()
