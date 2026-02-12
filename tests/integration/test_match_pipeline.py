# ABOUTME: Full pipeline integration tests for the match workflow.
# ABOUTME: Tests EPUB → provider → score → review → copy with updated metadata end-to-end.

from pathlib import Path
from typing import Any

from bookery.cli.review import ReviewSession
from bookery.core.pipeline import apply_metadata_safely
from bookery.formats.epub import read_epub_metadata
from bookery.metadata import BookMetadata
from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.openlibrary import OpenLibraryProvider
from tests.fixtures.openlibrary_responses import (
    AUTHOR_RESPONSE,
    ISBN_RESPONSE,
    SEARCH_RESPONSE,
    WORKS_RESPONSE_STR_DESCRIPTION,
)


class FakeHttpClient:
    """Fake HTTP client returning canned responses for integration tests."""

    def __init__(self, responses: dict[str, Any]) -> None:
        self._responses = responses

    def get(self, url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        for pattern, response in self._responses.items():
            if pattern in url:
                return response
        return {}


class TestFullMatchPipeline:
    """Integration tests for the complete match pipeline."""

    def test_epub_to_matched_copy(self, sample_epub: Path, tmp_path: Path) -> None:
        """Full pipeline: read EPUB → match via provider → write updated copy."""
        # Read extracted metadata
        extracted = read_epub_metadata(sample_epub)
        assert extracted.title == "The Name of the Rose"

        # Provider search
        client = FakeHttpClient({"/search.json": SEARCH_RESPONSE})
        provider = OpenLibraryProvider(http_client=client)
        candidates = provider.search_by_title_author(extracted.title, extracted.author)
        assert len(candidates) > 0

        # Select best candidate (simulate quiet mode)
        best = candidates[0]
        assert best.confidence > 0.5

        # Write updated copy
        output_dir = tmp_path / "output"
        result = apply_metadata_safely(sample_epub, best.metadata, output_dir)

        # Verify copy has updated metadata
        updated = read_epub_metadata(result)
        assert updated.title == best.metadata.title

    def test_original_is_byte_identical(self, sample_epub: Path, tmp_path: Path) -> None:
        """Original EPUB is byte-identical after the full pipeline."""
        original_bytes = sample_epub.read_bytes()

        # Run pipeline
        client = FakeHttpClient({"/search.json": SEARCH_RESPONSE})
        provider = OpenLibraryProvider(http_client=client)
        extracted = read_epub_metadata(sample_epub)
        candidates = provider.search_by_title_author(extracted.title)
        best = candidates[0]

        output_dir = tmp_path / "output"
        apply_metadata_safely(sample_epub, best.metadata, output_dir)

        # Verify original untouched
        assert sample_epub.read_bytes() == original_bytes

    def test_isbn_pipeline_enriches_metadata(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        """ISBN pipeline enriches metadata with description and author from OL."""
        client = FakeHttpClient(
            {
                "/isbn/": ISBN_RESPONSE,
                "/works/": WORKS_RESPONSE_STR_DESCRIPTION,
                "/authors/": AUTHOR_RESPONSE,
            }
        )
        provider = OpenLibraryProvider(http_client=client)
        candidates = provider.search_by_isbn("9780156001311")

        assert len(candidates) == 1
        meta = candidates[0].metadata
        assert meta.title == "The Name of the Rose"
        assert meta.authors == ["Umberto Eco"]
        assert meta.description is not None

        # Write and verify
        output_dir = tmp_path / "output"
        result = apply_metadata_safely(sample_epub, meta, output_dir)
        updated = read_epub_metadata(result)
        assert updated.title == "The Name of the Rose"
        assert "Umberto Eco" in updated.authors

    def test_quiet_review_auto_accepts(self) -> None:
        """ReviewSession in quiet mode auto-accepts high-confidence candidates."""
        extracted = BookMetadata(title="Old")
        candidate = MetadataCandidate(
            metadata=BookMetadata(title="Matched", authors=["Author"]),
            confidence=0.92,
            source="openlibrary",
            source_id="test",
        )

        session = ReviewSession(quiet=True, threshold=0.8)
        result = session.review(extracted, [candidate])

        assert result is not None
        assert result.title == "Matched"
