# ABOUTME: Google Books metadata provider implementation.
# ABOUTME: Searches Google Books v1 API by ISBN or title/author and returns scored candidates.

import logging
import re
from typing import Any

from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.http import HttpClient, MetadataFetchError
from bookery.metadata.scoring import score_candidate
from bookery.metadata.types import BookMetadata

logger = logging.getLogger(__name__)

_GB_BASE = "https://www.googleapis.com/books/v1/volumes"
_SEARCH_LIMIT = 5
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    return re.sub(r"\s+", " ", _HTML_TAG_RE.sub("", text)).strip()


def _pick_isbn(industry_identifiers: list[dict[str, str]]) -> str | None:
    """Return ISBN_13 if available, else ISBN_10, else None."""
    isbn_13 = None
    isbn_10 = None
    for ident in industry_identifiers:
        ident_type = ident.get("type", "")
        value = ident.get("identifier", "")
        if ident_type == "ISBN_13" and not isbn_13:
            isbn_13 = value
        elif ident_type == "ISBN_10" and not isbn_10:
            isbn_10 = value
    return isbn_13 or isbn_10


def _parse_volume(item: dict[str, Any]) -> BookMetadata:
    """Parse a Google Books `volumes` item into BookMetadata."""
    volume_info = item.get("volumeInfo", {}) or {}

    title = volume_info.get("title", "Unknown")
    subtitle = volume_info.get("subtitle")
    if subtitle:
        title = f"{title}: {subtitle}"

    authors = list(volume_info.get("authors", []) or [])

    publisher = volume_info.get("publisher")
    published_date = volume_info.get("publishedDate")
    language = volume_info.get("language")
    page_count = volume_info.get("pageCount")
    page_count = int(page_count) if isinstance(page_count, (int, float)) else None

    description = volume_info.get("description")
    if description:
        description = _strip_html(description)

    subjects = list(volume_info.get("categories", []) or [])

    isbn = _pick_isbn(volume_info.get("industryIdentifiers", []) or [])

    image_links = volume_info.get("imageLinks", {}) or {}
    cover_url = (
        image_links.get("thumbnail")
        or image_links.get("smallThumbnail")
        or None
    )
    if cover_url and cover_url.startswith("http://"):
        cover_url = "https://" + cover_url[len("http://") :]

    identifiers: dict[str, str] = {}
    volume_id = item.get("id")
    if volume_id:
        identifiers["googlebooks_volume"] = volume_id

    return BookMetadata(
        title=title,
        authors=authors,
        publisher=publisher,
        isbn=isbn,
        language=language,
        description=description,
        subjects=subjects,
        identifiers=identifiers,
        published_date=published_date,
        page_count=page_count,
        cover_url=cover_url,
    )


class GoogleBooksProvider:
    """Metadata provider backed by the Google Books v1 API.

    No auth required for the query endpoints we use. Fills in publishedDate,
    pageCount, and cover thumbnails that Open Library routinely lacks.
    """

    def __init__(self, http_client: HttpClient) -> None:
        self._http = http_client

    @property
    def name(self) -> str:
        return "googlebooks"

    def search_by_isbn(self, isbn: str) -> list[MetadataCandidate]:
        """Look up a book by ISBN via Google Books.

        Returns a single-element list on success, empty list on failure.
        """
        clean_isbn = re.sub(r"[\s-]", "", isbn)
        try:
            data = self._http.get(_GB_BASE, params={"q": f"isbn:{clean_isbn}"})
        except MetadataFetchError as exc:
            logger.warning("ISBN lookup failed for %s: %s", isbn, exc)
            return []

        items = data.get("items", []) or []
        if not items:
            return []

        metadata = _parse_volume(items[0])
        source_id = metadata.identifiers.get("googlebooks_volume", f"isbn:{clean_isbn}")
        return [
            MetadataCandidate(
                metadata=metadata,
                confidence=1.0,
                source=self.name,
                source_id=source_id,
            )
        ]

    def search_by_title_author(
        self, title: str, author: str | None = None
    ) -> list[MetadataCandidate]:
        """Search Google Books by title and optional author."""
        query_parts = [f"intitle:{title}"]
        if author:
            query_parts.append(f"inauthor:{author}")
        query = "+".join(query_parts)

        try:
            data = self._http.get(
                _GB_BASE,
                params={"q": query, "maxResults": str(_SEARCH_LIMIT)},
            )
        except MetadataFetchError as exc:
            logger.warning("Search failed for title=%s author=%s: %s", title, author, exc)
            return []

        items = data.get("items", []) or []
        if not items:
            return []

        query_meta = BookMetadata(
            title=title,
            authors=[author] if author else [],
        )

        candidates: list[MetadataCandidate] = []
        for item in items:
            meta = _parse_volume(item)
            confidence = score_candidate(query_meta, meta)
            source_id = meta.identifiers.get("googlebooks_volume", "unknown")
            candidates.append(
                MetadataCandidate(
                    metadata=meta,
                    confidence=confidence,
                    source=self.name,
                    source_id=source_id,
                )
            )

        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates

    def lookup_by_url(self, url: str) -> MetadataCandidate | None:
        """Look up metadata from a Google Books volume URL.

        Supports:
          https://books.google.com/books?id=VOLUME_ID
          https://www.google.com/books/edition/_/VOLUME_ID
          https://books.google.com/books/about/Title.html?id=VOLUME_ID
        """
        volume_id = self._parse_volume_id(url)
        if not volume_id:
            return None
        try:
            data = self._http.get(f"{_GB_BASE}/{volume_id}")
        except MetadataFetchError as exc:
            logger.warning("URL lookup failed for %s: %s", url, exc)
            return None

        metadata = _parse_volume(data)
        return MetadataCandidate(
            metadata=metadata,
            confidence=1.0,
            source=self.name,
            source_id=volume_id,
        )

    @staticmethod
    def _parse_volume_id(url: str) -> str | None:
        """Extract a Google Books volume id from a URL."""
        match = re.search(r"[?&]id=([A-Za-z0-9_-]+)", url)
        if match:
            return match.group(1)
        match = re.search(r"/books/edition/[^/]+/([A-Za-z0-9_-]+)", url)
        if match:
            return match.group(1)
        return None
