# ABOUTME: Hardcover metadata provider implementation.
# ABOUTME: GraphQL lookups by ISBN or title/author; strongest source for series info.

import logging
from typing import Any

from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.http import JsonPostClient, MetadataFetchError
from bookery.metadata.scoring import score_candidate
from bookery.metadata.types import BookMetadata

logger = logging.getLogger(__name__)

_HC_ENDPOINT = "https://api.hardcover.app/v1/graphql"
_SEARCH_LIMIT = 5

# If the live schema rejects featured_book_series, the older field name is
# book_series (list of {position, series {name}}); _parse_series handles both
# shapes so only the query string would need the swap.
_BOOK_FIELDS = """
    id
    title
    subtitle
    description
    rating
    ratings_count
    cached_image
    slug
    contributions {
      author { name }
      contribution
    }
    featured_book_series {
      position
      series { name }
    }
"""

_EDITION_FIELDS = """
    isbn_13
    isbn_10
    pages
    release_date
    publisher { name }
"""

_ISBN_QUERY = f"""
query FindByIsbn($isbn: String!) {{
  editions(
    where: {{_or: [{{isbn_10: {{_eq: $isbn}}}}, {{isbn_13: {{_eq: $isbn}}}}]}},
    limit: 1
  ) {{
    {_EDITION_FIELDS}
    book {{ {_BOOK_FIELDS} }}
  }}
}}
"""

_SEARCH_QUERY = """
query Search($query: String!, $perPage: Int!) {
  search(query: $query, query_type: "Book", per_page: $perPage) {
    ids
  }
}
"""

_BOOKS_BY_IDS_QUERY = f"""
query BooksByIds($ids: [Int!]) {{
  books(where: {{id: {{_in: $ids}}}}, order_by: {{users_read_count: desc_nulls_last}}) {{
    {_BOOK_FIELDS}
    editions(order_by: {{users_count: desc_nulls_last}}, limit: 1) {{
      {_EDITION_FIELDS}
    }}
  }}
}}
"""


def _normalize_isbn(isbn: str) -> str:
    return "".join(ch for ch in isbn if ch.isalnum()).upper()


def _parse_series(book: dict[str, Any]) -> tuple[str | None, float | None]:
    """Extract (series, series_index) from featured_book_series or book_series."""
    raw = book.get("featured_book_series") or book.get("book_series")
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if not isinstance(raw, dict):
        return None, None
    series = (raw.get("series") or {}).get("name") or None
    position = raw.get("position")
    series_index = float(position) if isinstance(position, (int, float)) else None
    return series, series_index


def _parse_authors(book: dict[str, Any]) -> list[str]:
    """Keep primary authors; Hardcover marks them with contribution None or "Author"."""
    authors: list[str] = []
    for contribution in book.get("contributions") or []:
        role = contribution.get("contribution")
        if role not in (None, "Author"):
            continue
        name = (contribution.get("author") or {}).get("name")
        if name:
            authors.append(name)
    return authors


def _parse_book(book: dict[str, Any], edition: dict[str, Any] | None) -> BookMetadata:
    """Map a Hardcover book (plus optional edition) into BookMetadata."""
    edition = edition or {}
    series, series_index = _parse_series(book)

    rating = book.get("rating")
    ratings_count = book.get("ratings_count")
    pages = edition.get("pages")
    cached_image = book.get("cached_image") or {}
    cover_url = cached_image.get("url") if isinstance(cached_image, dict) else None

    identifiers: dict[str, str] = {}
    if book.get("id") is not None:
        identifiers["hardcover_book"] = str(book["id"])
    if book.get("slug"):
        identifiers["hardcover_slug"] = book["slug"]

    return BookMetadata(
        title=book.get("title") or "Unknown",
        subtitle=book.get("subtitle") or None,
        authors=_parse_authors(book),
        publisher=(edition.get("publisher") or {}).get("name"),
        isbn=edition.get("isbn_13") or edition.get("isbn_10"),
        description=book.get("description") or None,
        identifiers=identifiers,
        published_date=edition.get("release_date"),
        page_count=int(pages) if isinstance(pages, (int, float)) and pages > 0 else None,
        cover_url=cover_url,
        rating=float(rating) if isinstance(rating, (int, float)) else None,
        ratings_count=int(ratings_count) if isinstance(ratings_count, (int, float)) else None,
        series=series,
        series_index=series_index,
    )


class HardcoverProvider:
    """Metadata provider backed by the Hardcover GraphQL API.

    Requires an API token (hardcover.app account settings). Without one the
    provider stays constructed but every search returns no candidates.
    Rate limit is 60 requests/minute; 429s are retried by the HTTP layer.
    """

    def __init__(self, http_client: JsonPostClient, token: str | None = None) -> None:
        self._http = http_client
        self._token = token
        self._warned_no_token = False

    @property
    def name(self) -> str:
        return "hardcover"

    def search_by_isbn(self, isbn: str) -> list[MetadataCandidate]:
        """Look up a single edition by ISBN-10 or ISBN-13."""
        data = self._post(_ISBN_QUERY, {"isbn": _normalize_isbn(isbn)})
        if data is None:
            return []

        editions = data.get("editions") or []
        if not editions:
            return []

        edition = editions[0]
        book = edition.get("book") or {}
        metadata = _parse_book(book, edition)
        return [
            MetadataCandidate(
                metadata=metadata,
                confidence=1.0,
                source=self.name,
                source_id=metadata.identifiers.get("hardcover_book", "unknown"),
            )
        ]

    def search_by_title_author(
        self, title: str, author: str | None = None
    ) -> list[MetadataCandidate]:
        """Search by title (and optional author), then hydrate books by id."""
        query = f"{title} {author}" if author else title
        data = self._post(_SEARCH_QUERY, {"query": query, "perPage": _SEARCH_LIMIT})
        if data is None:
            return []

        raw_ids = (data.get("search") or {}).get("ids") or []
        ids = [int(i) for i in raw_ids if str(i).isdigit()]
        if not ids:
            return []

        data = self._post(_BOOKS_BY_IDS_QUERY, {"ids": ids})
        if data is None:
            return []

        query_meta = BookMetadata(title=title, authors=[author] if author else [])
        candidates: list[MetadataCandidate] = []
        for book in data.get("books") or []:
            editions = book.get("editions") or []
            metadata = _parse_book(book, editions[0] if editions else None)
            candidates.append(
                MetadataCandidate(
                    metadata=metadata,
                    confidence=score_candidate(query_meta, metadata),
                    source=self.name,
                    source_id=metadata.identifiers.get("hardcover_book", "unknown"),
                )
            )

        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates

    def lookup_by_url(self, url: str) -> MetadataCandidate | None:
        """URL lookup is not supported for Hardcover."""
        return None

    def _post(self, query: str, variables: dict[str, Any]) -> dict[str, Any] | None:
        """Run a GraphQL query; returns the `data` object or None on any failure."""
        if not self._token:
            if not self._warned_no_token:
                logger.warning(
                    "hardcover provider configured but HARDCOVER_API_KEY is not set; "
                    "skipping all Hardcover lookups"
                )
                self._warned_no_token = True
            return None

        try:
            response = self._http.post_json(
                _HC_ENDPOINT,
                {"query": query, "variables": variables},
                headers={"Authorization": f"Bearer {self._token}"},
            )
        except MetadataFetchError as exc:
            logger.warning("Hardcover request failed: %s", exc)
            return None

        errors = response.get("errors")
        if errors:
            messages = "; ".join(str(e.get("message", e)) for e in errors)
            logger.warning("Hardcover GraphQL errors: %s", messages)
            return None

        return response.get("data") or {}
