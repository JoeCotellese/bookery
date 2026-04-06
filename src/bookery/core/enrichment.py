# ABOUTME: Enrichment service facade for TUI metadata search and apply.
# ABOUTME: Thin wrapper over existing providers, normalizer, and write pipeline.

import logging
from pathlib import Path

from bookery.core.pipeline import WriteResult, apply_metadata_safely
from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.normalizer import normalize_metadata
from bookery.metadata.provider import MetadataProvider
from bookery.metadata.types import BookMetadata

logger = logging.getLogger(__name__)


class EnrichmentService:
    """Facade for metadata enrichment operations.

    Provides search and apply methods that the TUI calls via background
    workers. All methods are synchronous — the TUI wraps them in
    run_worker(thread=True) for non-blocking operation.
    """

    def __init__(self, provider: MetadataProvider, output_dir: Path) -> None:
        self._provider = provider
        self._output_dir = output_dir

    def search(self, metadata: BookMetadata) -> list[MetadataCandidate]:
        """Search for metadata candidates using ISBN-first, title/author fallback.

        Normalizes mangled metadata before searching for better query quality.
        """
        norm_result = normalize_metadata(metadata)
        search_meta = norm_result.normalized

        if norm_result.was_modified:
            logger.debug(
                "enrichment search: normalized title=%r author=%r",
                search_meta.title,
                search_meta.author,
            )

        # ISBN lookup first
        candidates: list[MetadataCandidate] = []
        if search_meta.isbn:
            candidates = self._provider.search_by_isbn(search_meta.isbn)
            logger.debug("enrichment search: ISBN returned %d candidates", len(candidates))

        # Fall back to title/author
        if not candidates:
            author = search_meta.author or None
            candidates = self._provider.search_by_title_author(search_meta.title, author)
            logger.debug(
                "enrichment search: title/author returned %d candidates", len(candidates)
            )

        return candidates

    def search_manual(self, query: str) -> list[MetadataCandidate]:
        """Search by free text or auto-detected Open Library URL.

        URLs (starting with http:// or https://) are dispatched to
        lookup_by_url. Plain text queries search by title/author.
        """
        if query.startswith(("http://", "https://")):
            candidate = self._provider.lookup_by_url(query)
            return [candidate] if candidate else []

        return self._provider.search_by_title_author(query, None)

    def lookup_url(self, url: str) -> MetadataCandidate | None:
        """Look up metadata from an Open Library URL."""
        return self._provider.lookup_by_url(url)

    def apply(self, source: Path, metadata: BookMetadata) -> WriteResult:
        """Write enriched metadata to a non-destructive copy.

        Delegates to apply_metadata_safely. Catalog DB updates should
        be performed by the caller on the main thread.
        """
        return apply_metadata_safely(source, metadata, self._output_dir)
