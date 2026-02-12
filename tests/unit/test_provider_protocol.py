# ABOUTME: Unit tests for MetadataProvider protocol.
# ABOUTME: Validates the protocol contract and runtime_checkable behavior.

from bookery.metadata import BookMetadata
from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.provider import MetadataProvider


class FakeProvider:
    """Minimal implementation of MetadataProvider for testing."""

    @property
    def name(self) -> str:
        return "fake"

    def search_by_isbn(self, isbn: str) -> list[MetadataCandidate]:
        return [
            MetadataCandidate(
                metadata=BookMetadata(title="Found by ISBN"),
                confidence=0.95,
                source="fake",
                source_id="isbn-123",
            )
        ]

    def search_by_title_author(
        self, title: str, author: str | None = None
    ) -> list[MetadataCandidate]:
        return []

    def lookup_by_url(self, url: str) -> MetadataCandidate | None:
        return None


class NotAProvider:
    """Missing required methods — should not satisfy the protocol."""

    @property
    def name(self) -> str:
        return "broken"


class TestMetadataProvider:
    """Tests for MetadataProvider protocol."""

    def test_valid_implementation_is_instance(self) -> None:
        """A class with all required methods satisfies the protocol."""
        provider = FakeProvider()
        assert isinstance(provider, MetadataProvider)

    def test_invalid_implementation_is_not_instance(self) -> None:
        """A class missing required methods does not satisfy the protocol."""
        broken = NotAProvider()
        assert not isinstance(broken, MetadataProvider)

    def test_search_by_isbn_returns_candidates(self) -> None:
        """search_by_isbn returns a list of MetadataCandidate."""
        provider = FakeProvider()
        results = provider.search_by_isbn("978-0-123456-47-2")
        assert len(results) == 1
        assert results[0].metadata.title == "Found by ISBN"

    def test_search_by_title_author_returns_list(self) -> None:
        """search_by_title_author returns a (possibly empty) list."""
        provider = FakeProvider()
        results = provider.search_by_title_author("Nonexistent", "Nobody")
        assert results == []
