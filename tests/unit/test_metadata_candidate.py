# ABOUTME: Unit tests for MetadataCandidate dataclass.
# ABOUTME: Validates construction, confidence bounds, and field access.

import pytest

from bookery.metadata import BookMetadata
from bookery.metadata.candidate import MetadataCandidate


class TestMetadataCandidate:
    """Tests for MetadataCandidate dataclass."""

    def test_construction_with_valid_confidence(self) -> None:
        """A candidate wraps BookMetadata with confidence and source info."""
        meta = BookMetadata(title="The Name of the Rose", authors=["Umberto Eco"])
        candidate = MetadataCandidate(
            metadata=meta,
            confidence=0.85,
            source="openlibrary",
            source_id="OL123W",
        )
        assert candidate.metadata.title == "The Name of the Rose"
        assert candidate.confidence == 0.85
        assert candidate.source == "openlibrary"
        assert candidate.source_id == "OL123W"

    def test_confidence_at_boundaries(self) -> None:
        """Confidence of exactly 0.0 and 1.0 are valid."""
        meta = BookMetadata(title="Test")
        low = MetadataCandidate(metadata=meta, confidence=0.0, source="test", source_id="1")
        high = MetadataCandidate(metadata=meta, confidence=1.0, source="test", source_id="2")
        assert low.confidence == 0.0
        assert high.confidence == 1.0

    def test_confidence_below_zero_raises(self) -> None:
        """Confidence below 0.0 raises ValueError."""
        meta = BookMetadata(title="Test")
        with pytest.raises(ValueError, match="confidence"):
            MetadataCandidate(metadata=meta, confidence=-0.1, source="test", source_id="1")

    def test_confidence_above_one_raises(self) -> None:
        """Confidence above 1.0 raises ValueError."""
        meta = BookMetadata(title="Test")
        with pytest.raises(ValueError, match="confidence"):
            MetadataCandidate(metadata=meta, confidence=1.1, source="test", source_id="1")
