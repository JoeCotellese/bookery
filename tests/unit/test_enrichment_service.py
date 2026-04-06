# ABOUTME: Unit tests for the EnrichmentService core facade.
# ABOUTME: Verifies search delegation, normalization, manual search, URL lookup, and apply.

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bookery.core.enrichment import EnrichmentService
from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.types import BookMetadata


@pytest.fixture
def provider() -> MagicMock:
    """Create a mock MetadataProvider."""
    mock = MagicMock()
    mock.name = "mock_provider"
    mock.search_by_isbn.return_value = []
    mock.search_by_title_author.return_value = []
    mock.lookup_by_url.return_value = None
    return mock


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    """Create a temporary output directory."""
    d = tmp_path / "output"
    d.mkdir()
    return d


@pytest.fixture
def service(provider: MagicMock, output_dir: Path) -> EnrichmentService:
    """Create an EnrichmentService with mock provider."""
    return EnrichmentService(provider=provider, output_dir=output_dir)


def _make_candidate(
    title: str = "Test Book",
    confidence: float = 0.9,
    source: str = "test",
) -> MetadataCandidate:
    """Create a test MetadataCandidate."""
    return MetadataCandidate(
        metadata=BookMetadata(title=title, authors=["Test Author"]),
        confidence=confidence,
        source=source,
        source_id="test-id",
    )


class TestEnrichmentServiceSearch:
    """Tests for EnrichmentService.search()."""

    def test_search_by_isbn_when_isbn_present(
        self, service: EnrichmentService, provider: MagicMock
    ) -> None:
        """search() delegates to search_by_isbn when metadata has ISBN."""
        candidate = _make_candidate()
        provider.search_by_isbn.return_value = [candidate]

        metadata = BookMetadata(title="Test", isbn="978-0-123456-47-2")
        result = service.search(metadata)

        provider.search_by_isbn.assert_called_once_with("978-0-123456-47-2")
        assert result == [candidate]

    def test_search_falls_back_to_title_author(
        self, service: EnrichmentService, provider: MagicMock
    ) -> None:
        """search() falls back to title/author when ISBN search returns nothing."""
        candidate = _make_candidate()
        provider.search_by_isbn.return_value = []
        provider.search_by_title_author.return_value = [candidate]

        metadata = BookMetadata(
            title="The Name of the Rose",
            authors=["Umberto Eco"],
            isbn="978-0-123456-47-2",
        )
        result = service.search(metadata)

        provider.search_by_title_author.assert_called_once()
        assert result == [candidate]

    def test_search_title_author_when_no_isbn(
        self, service: EnrichmentService, provider: MagicMock
    ) -> None:
        """search() goes straight to title/author when no ISBN present."""
        candidate = _make_candidate()
        provider.search_by_title_author.return_value = [candidate]

        metadata = BookMetadata(title="Dune", authors=["Frank Herbert"])
        result = service.search(metadata)

        provider.search_by_isbn.assert_not_called()
        provider.search_by_title_author.assert_called_once_with("Dune", "Frank Herbert")
        assert result == [candidate]

    def test_search_normalizes_metadata(
        self, service: EnrichmentService, provider: MagicMock
    ) -> None:
        """search() normalizes mangled metadata before searching."""
        provider.search_by_title_author.return_value = []

        # CamelCase title that needs normalization
        metadata = BookMetadata(title="TheNameOfTheRose", authors=[])
        service.search(metadata)

        # The provider should receive normalized (split) title, not the raw one
        call_args = provider.search_by_title_author.call_args
        title_arg = call_args[0][0]
        assert " " in title_arg  # Normalized title should have spaces

    def test_search_returns_empty_when_no_candidates(
        self, service: EnrichmentService, provider: MagicMock
    ) -> None:
        """search() returns empty list when no candidates found."""
        metadata = BookMetadata(title="Nonexistent Book")
        result = service.search(metadata)
        assert result == []

    def test_search_author_none_when_no_authors(
        self, service: EnrichmentService, provider: MagicMock
    ) -> None:
        """search() passes None as author when metadata has no authors."""
        provider.search_by_title_author.return_value = []

        metadata = BookMetadata(title="Mystery Book", authors=[])
        service.search(metadata)

        provider.search_by_title_author.assert_called_once_with("Mystery Book", None)


class TestEnrichmentServiceManualSearch:
    """Tests for EnrichmentService.search_manual()."""

    def test_manual_text_search(
        self, service: EnrichmentService, provider: MagicMock
    ) -> None:
        """search_manual() with plain text delegates to search_by_title_author."""
        candidate = _make_candidate()
        provider.search_by_title_author.return_value = [candidate]

        result = service.search_manual("Italo Calvino")

        provider.search_by_title_author.assert_called_once_with("Italo Calvino", None)
        assert result == [candidate]

    def test_manual_url_detected(
        self, service: EnrichmentService, provider: MagicMock
    ) -> None:
        """search_manual() auto-detects URLs and delegates to lookup_by_url."""
        candidate = _make_candidate()
        provider.lookup_by_url.return_value = candidate

        url = "https://openlibrary.org/works/OL123W"
        result = service.search_manual(url)

        provider.lookup_by_url.assert_called_once_with(url)
        assert result == [candidate]

    def test_manual_url_returns_empty_on_failure(
        self, service: EnrichmentService, provider: MagicMock
    ) -> None:
        """search_manual() with URL returns empty list when lookup fails."""
        provider.lookup_by_url.return_value = None

        result = service.search_manual("https://openlibrary.org/works/OL999W")

        assert result == []

    def test_manual_http_url_detected(
        self, service: EnrichmentService, provider: MagicMock
    ) -> None:
        """search_manual() detects http:// URLs (not just https://)."""
        candidate = _make_candidate()
        provider.lookup_by_url.return_value = candidate

        url = "http://openlibrary.org/works/OL123W"
        service.search_manual(url)

        provider.lookup_by_url.assert_called_once_with(url)


class TestEnrichmentServiceLookupUrl:
    """Tests for EnrichmentService.lookup_url()."""

    def test_delegates_to_provider(
        self, service: EnrichmentService, provider: MagicMock
    ) -> None:
        """lookup_url() delegates to provider.lookup_by_url."""
        candidate = _make_candidate()
        provider.lookup_by_url.return_value = candidate

        result = service.lookup_url("https://openlibrary.org/works/OL123W")

        provider.lookup_by_url.assert_called_once_with(
            "https://openlibrary.org/works/OL123W"
        )
        assert result == candidate

    def test_returns_none_on_failure(
        self, service: EnrichmentService, provider: MagicMock
    ) -> None:
        """lookup_url() returns None when provider lookup fails."""
        provider.lookup_by_url.return_value = None

        result = service.lookup_url("https://openlibrary.org/works/OL999W")
        assert result is None


class TestEnrichmentServiceApply:
    """Tests for EnrichmentService.apply()."""

    def test_delegates_to_apply_metadata_safely(
        self, service: EnrichmentService, output_dir: Path
    ) -> None:
        """apply() delegates to apply_metadata_safely with correct args."""
        source = Path("/books/test.epub")
        metadata = BookMetadata(title="Test Book")

        with patch("bookery.core.enrichment.apply_metadata_safely") as mock_apply:
            mock_apply.return_value = MagicMock(
                success=True, path=output_dir / "test.epub"
            )
            result = service.apply(source, metadata)

        mock_apply.assert_called_once_with(source, metadata, output_dir)
        assert result.success is True

    def test_apply_returns_write_result(
        self, service: EnrichmentService, output_dir: Path
    ) -> None:
        """apply() returns the WriteResult from apply_metadata_safely."""
        source = Path("/books/test.epub")
        metadata = BookMetadata(title="Test Book")

        with patch("bookery.core.enrichment.apply_metadata_safely") as mock_apply:
            mock_apply.return_value = MagicMock(
                success=False, error="Write failed", path=None
            )
            result = service.apply(source, metadata)

        assert result.success is False
        assert result.error == "Write failed"
