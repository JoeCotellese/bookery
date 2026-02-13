# ABOUTME: Unit tests for the library verification logic.
# ABOUTME: Validates file existence checks, hash verification, and result aggregation.

from pathlib import Path

import pytest

from bookery.core.verifier import VerifyResult, verify_library
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


@pytest.fixture()
def catalog_with_books(tmp_path: Path):
    """Create a catalog with books that have real source files."""
    db_path = tmp_path / "verify_test.db"
    conn = open_library(db_path)
    catalog = LibraryCatalog(conn)

    # Create real source files
    source_a = tmp_path / "a.epub"
    source_a.write_text("content a")
    source_b = tmp_path / "b.epub"
    source_b.write_text("content b")

    catalog.add_book(
        BookMetadata(title="Book A", source_path=source_a),
        file_hash="hash_a",
    )
    catalog.add_book(
        BookMetadata(title="Book B", source_path=source_b),
        file_hash="hash_b",
    )

    return catalog


class TestVerifyResult:
    """Tests for the VerifyResult dataclass."""

    def test_default_result_is_clean(self) -> None:
        """A default VerifyResult has no issues."""
        result = VerifyResult()
        assert result.ok == 0
        assert result.missing_source == []
        assert result.missing_output == []
        assert result.hash_mismatch == []

    def test_total_issues(self) -> None:
        """total_issues counts all problem categories."""
        result = VerifyResult(ok=5, missing_source=["a"], missing_output=["b", "c"])
        assert result.total_issues == 3


class TestVerifyLibrary:
    """Tests for verify_library()."""

    def test_all_files_present(self, catalog_with_books: LibraryCatalog) -> None:
        """Verify succeeds when all source files exist."""
        result = verify_library(catalog_with_books)
        assert result.ok == 2
        assert result.missing_source == []

    def test_missing_source_detected(self, tmp_path: Path) -> None:
        """Books with missing source_path are flagged."""
        db_path = tmp_path / "missing.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)

        catalog.add_book(
            BookMetadata(title="Ghost Book", source_path=Path("/nonexistent/ghost.epub")),
            file_hash="ghost_hash",
        )

        result = verify_library(catalog)
        assert result.ok == 0
        assert len(result.missing_source) == 1
        assert result.missing_source[0].metadata.title == "Ghost Book"

    def test_missing_output_detected(self, tmp_path: Path) -> None:
        """Books with output_path set but file missing are flagged."""
        db_path = tmp_path / "output.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)

        source = tmp_path / "real.epub"
        source.write_text("real content")

        book_id = catalog.add_book(
            BookMetadata(title="Outputless Book", source_path=source),
            file_hash="real_hash",
        )
        catalog.set_output_path(book_id, Path("/nonexistent/output.epub"))

        result = verify_library(catalog)
        assert result.ok == 0
        assert len(result.missing_output) == 1
        assert result.missing_output[0].metadata.title == "Outputless Book"

    def test_no_output_path_is_ok(self, tmp_path: Path) -> None:
        """Books without output_path are not flagged for missing output."""
        db_path = tmp_path / "noout.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)

        source = tmp_path / "ok.epub"
        source.write_text("ok content")

        catalog.add_book(
            BookMetadata(title="No Output", source_path=source),
            file_hash="ok_hash",
        )

        result = verify_library(catalog)
        assert result.ok == 1
        assert result.missing_output == []

    def test_hash_mismatch_detected(self, tmp_path: Path) -> None:
        """Books with changed source file are flagged when check_hash=True."""
        db_path = tmp_path / "hashcheck.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)

        source = tmp_path / "changed.epub"
        source.write_text("original content")

        from bookery.db.hashing import compute_file_hash

        original_hash = compute_file_hash(source)

        catalog.add_book(
            BookMetadata(title="Changed Book", source_path=source),
            file_hash=original_hash,
        )

        # Modify the file after import
        source.write_text("modified content")

        result = verify_library(catalog, check_hash=True)
        assert len(result.hash_mismatch) == 1
        assert result.hash_mismatch[0].metadata.title == "Changed Book"

    def test_hash_check_skipped_by_default(self, tmp_path: Path) -> None:
        """Hash checking is off by default — modified files are not flagged."""
        db_path = tmp_path / "nohash.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)

        source = tmp_path / "maybe.epub"
        source.write_text("original")

        catalog.add_book(
            BookMetadata(title="Unchecked", source_path=source),
            file_hash="stale_hash",
        )

        source.write_text("modified")

        result = verify_library(catalog)
        assert result.hash_mismatch == []
        assert result.ok == 1

    def test_hash_check_skips_missing_source(self, tmp_path: Path) -> None:
        """Hash check doesn't fail if source file is already missing."""
        db_path = tmp_path / "skip.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)

        catalog.add_book(
            BookMetadata(title="Gone", source_path=Path("/gone/book.epub")),
            file_hash="gone_hash",
        )

        result = verify_library(catalog, check_hash=True)
        assert len(result.missing_source) == 1
        assert result.hash_mismatch == []

    def test_empty_library(self, tmp_path: Path) -> None:
        """Verifying an empty library returns clean result."""
        db_path = tmp_path / "empty.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)

        result = verify_library(catalog)
        assert result.ok == 0
        assert result.total_issues == 0
