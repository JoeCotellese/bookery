# ABOUTME: Open Library metadata provider implementation.
# ABOUTME: Searches openlibrary.org by ISBN or title/author and returns scored candidates.

import logging
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.http import HttpClient, MetadataFetchError
from bookery.metadata.openlibrary_parser import (
    parse_author_name,
    parse_isbn_response,
    parse_search_results,
    parse_works_metadata,
    parse_works_response,
    select_best_edition,
)
from bookery.metadata.scoring import score_candidate
from bookery.metadata.types import BookMetadata

logger = logging.getLogger(__name__)

_OL_BASE = "https://openlibrary.org"
_SEARCH_LIMIT = 5
_ENRICH_DESCRIPTION_LIMIT = 3

# Matches a colon followed by a space and remaining text (subtitle pattern).
_SUBTITLE_RE = re.compile(r"\s*:\s+.+$")


def _strip_subtitle(title: str) -> str | None:
    """Remove subtitle from a title string (text after ": ").

    Returns the stripped title, or None if no subtitle was found or
    stripping would produce an identical or empty string.
    """
    stripped = _SUBTITLE_RE.sub("", title).strip()
    if stripped and stripped != title.strip():
        return stripped
    return None


class OpenLibraryProvider:
    """Metadata provider backed by the Open Library API.

    Supports ISBN-based lookup (most precise) and title/author search (broader).
    Uses dependency-injected HttpClient for testability.
    """

    def __init__(self, http_client: HttpClient) -> None:
        self._http = http_client

    @property
    def name(self) -> str:
        return "openlibrary"

    def search_by_isbn(self, isbn: str) -> list[MetadataCandidate]:
        """Look up a book by ISBN via the Open Library ISBN endpoint.

        Follows up with works and author endpoints to enrich metadata.
        Returns a single-element list on success, empty list on failure.
        """
        clean_isbn = re.sub(r"[\s-]", "", isbn)
        try:
            data = self._http.get(f"{_OL_BASE}/isbn/{clean_isbn}.json")
        except MetadataFetchError as exc:
            logger.warning("ISBN lookup failed for %s: %s", isbn, exc)
            return []

        metadata = parse_isbn_response(data)
        metadata = self._enrich_from_works(metadata, data)
        metadata = self._enrich_authors(metadata, data)

        source_id = metadata.identifiers.get("openlibrary_work", f"isbn:{isbn}")
        candidate = MetadataCandidate(
            metadata=metadata,
            confidence=1.0,  # ISBN match is high-confidence by definition
            source=self.name,
            source_id=source_id,
        )
        return [candidate]

    def search_by_title_author(
        self, title: str, author: str | None = None
    ) -> list[MetadataCandidate]:
        """Search Open Library by title and optional author.

        If the initial search returns no results and the title contains a
        subtitle (text after ": "), retries with the subtitle stripped.
        Returns candidates sorted by confidence descending.
        """
        candidates = self._search_ol(title, author)
        if not candidates:
            stripped = _strip_subtitle(title)
            if stripped:
                candidates = self._search_ol(stripped, author)
        return candidates

    def _search_ol(self, title: str, author: str | None = None) -> list[MetadataCandidate]:
        """Execute a single Open Library search query.

        Returns candidates sorted by confidence descending, with top results
        enriched with descriptions from the works endpoint.
        """
        params: dict[str, str] = {"title": title, "limit": str(_SEARCH_LIMIT)}
        if author:
            params["author"] = author

        try:
            data = self._http.get(f"{_OL_BASE}/search.json", params=params)
        except MetadataFetchError as exc:
            logger.warning("Search failed for title=%s author=%s: %s", title, author, exc)
            return []

        search_metadata = parse_search_results(data)
        if not search_metadata:
            return []

        # Build a reference BookMetadata from the search terms for scoring
        query_meta = BookMetadata(
            title=title,
            authors=[author] if author else [],
        )

        candidates = []
        for meta in search_metadata:
            confidence = score_candidate(query_meta, meta)
            source_id = meta.identifiers.get("openlibrary_work", "unknown")
            candidates.append(
                MetadataCandidate(
                    metadata=meta,
                    confidence=confidence,
                    source=self.name,
                    source_id=source_id,
                )
            )

        candidates.sort(key=lambda c: c.confidence, reverse=True)
        self._enrich_descriptions(candidates)
        self._enrich_from_editions(candidates)
        return candidates

    def lookup_by_url(self, url: str) -> MetadataCandidate | None:
        """Look up metadata from an Open Library URL.

        Supports URLs like:
          https://openlibrary.org/works/OL123W/Title
          https://openlibrary.org/works/OL123W?edition=key:/books/OL456M

        Returns None on any parse or fetch failure.
        """
        parsed = self._parse_ol_url(url)
        if parsed is None:
            return None

        works_key, edition_key = parsed
        try:
            if edition_key:
                return self._lookup_by_edition(works_key, edition_key)
            return self._lookup_by_works(works_key)
        except MetadataFetchError as exc:
            logger.warning("URL lookup failed for %s: %s", url, exc)
            return None

    @staticmethod
    def _parse_ol_url(url: str) -> tuple[str, str | None] | None:
        """Extract works key and optional edition key from an OL URL.

        Returns (works_key, edition_key) or None if URL is not a valid OL works URL.
        """
        try:
            parsed = urlparse(url)
        except ValueError:
            return None

        if parsed.hostname != "openlibrary.org":
            return None

        # Extract works key from path: /works/OL123W or /works/OL123W/Title_Slug
        match = re.match(r"(/works/OL\w+)", parsed.path)
        if not match:
            return None
        works_key = match.group(1)

        # Check for edition key in query: edition=key:/books/OL456M
        edition_key = None
        qs = parse_qs(parsed.query)
        edition_values = qs.get("edition", [])
        if edition_values:
            edition_raw = edition_values[0]
            # Format: "key:/books/OL456M"
            if edition_raw.startswith("key:"):
                edition_key = edition_raw[4:]

        return works_key, edition_key

    def _lookup_by_edition(self, works_key: str, edition_key: str) -> MetadataCandidate:
        """Fetch full metadata from edition + works + author endpoints."""
        edition_data = self._http.get(f"{_OL_BASE}{edition_key}.json")
        metadata = parse_isbn_response(edition_data)
        metadata = self._enrich_from_works(metadata, edition_data)
        metadata = self._enrich_authors(metadata, edition_data)

        source_id = metadata.identifiers.get("openlibrary_work", works_key)
        return MetadataCandidate(
            metadata=metadata,
            confidence=1.0,
            source=self.name,
            source_id=source_id,
        )

    def _lookup_by_works(self, works_key: str) -> MetadataCandidate:
        """Fetch metadata from works endpoint only (no edition data)."""
        works_data = self._http.get(f"{_OL_BASE}{works_key}.json")
        metadata = parse_works_metadata(works_data)

        # Resolve author names from author keys stored by parse_works_metadata
        author_keys_str = metadata.identifiers.get("openlibrary_author_keys", "")
        if author_keys_str:
            del metadata.identifiers["openlibrary_author_keys"]
            authors: list[str] = []
            for author_key in author_keys_str.split(","):
                try:
                    author_data = self._http.get(f"{_OL_BASE}{author_key}.json")
                    authors.append(parse_author_name(author_data))
                except MetadataFetchError:
                    continue
            if authors:
                metadata.authors = authors

        return MetadataCandidate(
            metadata=metadata,
            confidence=1.0,
            source=self.name,
            source_id=works_key,
        )

    def _enrich_descriptions(self, candidates: list[MetadataCandidate]) -> None:
        """Fetch descriptions from the works endpoint for the top candidates.

        MUTATES candidates in place — sets metadata.description on enriched items.
        Only enriches candidates that have a works key and no description yet.
        """
        for candidate in candidates[:_ENRICH_DESCRIPTION_LIMIT]:
            if candidate.metadata.description is not None:
                continue
            works_key = candidate.metadata.identifiers.get("openlibrary_work")
            if not works_key:
                continue
            try:
                works_data = self._http.get(f"{_OL_BASE}{works_key}.json")
            except MetadataFetchError:
                continue
            description = parse_works_response(works_data)
            if description:
                candidate.metadata.description = description

    def _enrich_from_editions(self, candidates: list[MetadataCandidate]) -> None:
        """Fetch edition-level data (ISBN, publisher) for the top candidates.

        MUTATES candidates in place — fills missing isbn and publisher fields
        from the best available edition. Only enriches candidates that have a
        works key and are missing ISBN or publisher.
        """
        for candidate in candidates[:_ENRICH_DESCRIPTION_LIMIT]:
            if candidate.metadata.isbn and candidate.metadata.publisher:
                continue
            works_key = candidate.metadata.identifiers.get("openlibrary_work")
            if not works_key:
                continue
            try:
                editions_data = self._http.get(f"{_OL_BASE}{works_key}/editions.json")
            except MetadataFetchError:
                continue
            best = select_best_edition(editions_data.get("entries", []))
            if not best:
                continue
            if not candidate.metadata.isbn and best["isbn"]:
                candidate.metadata.isbn = best["isbn"]
            if not candidate.metadata.publisher and best["publisher"]:
                candidate.metadata.publisher = best["publisher"]

    def _enrich_from_works(
        self, metadata: BookMetadata, isbn_data: dict[str, Any]
    ) -> BookMetadata:
        """Fetch description from the works endpoint if available."""
        works = isbn_data.get("works", [])
        if not works:
            return metadata

        works_key = works[0].get("key", "")
        if not works_key:
            return metadata

        try:
            works_data = self._http.get(f"{_OL_BASE}{works_key}.json")
        except MetadataFetchError:
            return metadata

        description = parse_works_response(works_data)
        if description:
            metadata.description = description
        return metadata

    def _enrich_authors(self, metadata: BookMetadata, isbn_data: dict[str, Any]) -> BookMetadata:
        """Fetch author names from the authors endpoint."""
        author_entries = isbn_data.get("authors", [])
        if not author_entries:
            return metadata

        authors: list[str] = []
        for entry in author_entries:
            author_key = entry.get("key", "")
            if not author_key:
                continue
            try:
                author_data = self._http.get(f"{_OL_BASE}{author_key}.json")
                authors.append(parse_author_name(author_data))
            except MetadataFetchError:
                continue

        if authors:
            metadata.authors = authors
        return metadata
