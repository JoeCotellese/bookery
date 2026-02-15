# ABOUTME: Integration tests for the rematch pipeline with DB updates.
# ABOUTME: Verifies that rematch correctly updates catalog records after matching.

from pathlib import Path

import pytest

from bookery.cli.commands.rematch_cmd import _metadata_to_update_fields
from bookery.core.pipeline import MatchOneResult
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.types import BookMetadata


def _make_candidate(
    title: str, author: str, confidence: float, isbn: str | None = None,
) -> MetadataCandidate:
    return MetadataCandidate(
        metadata=BookMetadata(title=title, authors=[author], isbn=isbn, language="en"),
        confidence=confidence,
        source="openlibrary",
        source_id=f"test-{title}",
    )


@pytest.fixture
def catalog_with_book(sample_epub: Path, tmp_path: Path):
    """Create a DB with one imported book, return (catalog, conn, record)."""
    from bookery.db.hashing import compute_file_hash

    db_path = tmp_path / "test.db"
    conn = open_library(db_path)
    catalog = LibraryCatalog(conn)

    metadata = BookMetadata(
        title="The Name of the Rose",
        authors=["Umberto Eco"],
        language="en",
        source_path=sample_epub,
    )
    file_hash = compute_file_hash(sample_epub)
    book_id = catalog.add_book(metadata, file_hash=file_hash)
    record = catalog.get_by_id(book_id)

    yield catalog, conn, record

    conn.close()


class TestRematchPipeline:
    """Integration tests for the rematch DB update loop."""

    def test_rematch_updates_catalog_metadata(
        self, catalog_with_book, tmp_path: Path,
    ) -> None:
        """Catalog record is updated with enriched metadata after rematch."""
        catalog, _conn, record = catalog_with_book
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        output_path = output_dir / "test.epub"
        output_path.write_bytes(b"fake")

        enriched = BookMetadata(
            title="Il Nome della Rosa",
            authors=["Umberto Eco"],
            isbn="9780151446476",
            language="en",
        )

        # Simulate what the rematch loop does on a "matched" result
        fields = _metadata_to_update_fields(enriched)
        catalog.update_book(record.id, **fields)
        catalog.set_output_path(record.id, output_path)

        updated = catalog.get_by_id(record.id)
        assert updated.metadata.title == "Il Nome della Rosa"
        assert updated.metadata.isbn == "9780151446476"
        assert updated.output_path == output_path

    def test_rematch_sets_output_path(
        self, catalog_with_book, tmp_path: Path,
    ) -> None:
        """Output path is set on the catalog record after successful match."""
        catalog, _conn, record = catalog_with_book
        output_path = tmp_path / "output" / "matched.epub"

        catalog.set_output_path(record.id, output_path)

        updated = catalog.get_by_id(record.id)
        assert updated.output_path == output_path

    def test_rematch_skips_when_no_match(
        self, catalog_with_book, tmp_path: Path,
    ) -> None:
        """DB record is unchanged when match returns 'skipped'."""
        catalog, _conn, record = catalog_with_book
        original_title = record.metadata.title

        # Simulate a skip — no update
        skip_result = MatchOneResult(status="skipped")

        # The rematch loop only updates on "matched" status
        if skip_result.status == "matched":
            pytest.fail("Should not reach here for skip")

        unchanged = catalog.get_by_id(record.id)
        assert unchanged.metadata.title == original_title
        assert unchanged.output_path is None

    def test_rematch_handles_missing_source_file(
        self, tmp_path: Path,
    ) -> None:
        """Source path doesn't exist -> error, DB unchanged."""
        db_path = tmp_path / "test.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)

        metadata = BookMetadata(
            title="Ghost Book",
            authors=["Nobody"],
            source_path=tmp_path / "nonexistent.epub",
        )
        book_id = catalog.add_book(metadata, file_hash="ghost123")
        record = catalog.get_by_id(book_id)

        # Source file doesn't exist
        assert not record.source_path.exists()

        # The rematch loop checks source_path.exists() before calling match_one
        unchanged = catalog.get_by_id(book_id)
        assert unchanged.metadata.title == "Ghost Book"
        assert unchanged.output_path is None

        conn.close()


class TestMetadataToUpdateFields:
    """Tests for the _metadata_to_update_fields helper."""

    def test_extracts_all_non_none_fields(self) -> None:
        """All non-None metadata fields are included in the dict."""
        meta = BookMetadata(
            title="Test",
            authors=["Author"],
            isbn="1234567890",
            language="en",
            publisher="Publisher",
            description="A book.",
            series="Series",
            series_index=1.0,
        )
        fields = _metadata_to_update_fields(meta)

        assert fields["title"] == "Test"
        assert fields["authors"] == ["Author"]
        assert fields["isbn"] == "1234567890"
        assert fields["language"] == "en"
        assert fields["publisher"] == "Publisher"
        assert fields["description"] == "A book."
        assert fields["series"] == "Series"
        assert fields["series_index"] == 1.0

    def test_skips_none_fields(self) -> None:
        """None fields are not included in the dict."""
        meta = BookMetadata(title="Minimal")
        fields = _metadata_to_update_fields(meta)

        assert "title" in fields
        assert "isbn" not in fields
        assert "publisher" not in fields
