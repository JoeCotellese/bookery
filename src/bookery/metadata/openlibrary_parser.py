# ABOUTME: Parsing functions for Open Library API JSON responses.
# ABOUTME: Converts OL-specific data structures into BookMetadata instances.

from typing import Any

from bookery.metadata.types import BookMetadata

_COVERS_BASE_URL = "https://covers.openlibrary.org/b/isbn"


def parse_isbn_response(data: dict[str, Any]) -> BookMetadata:
    """Parse an Open Library ISBN endpoint response into BookMetadata.

    The ISBN endpoint returns edition-level data with fields like
    title, publishers, isbn_13, languages, works, etc.
    """
    title = data.get("title", "Unknown")

    publishers = data.get("publishers", [])
    publisher = publishers[0] if publishers else None

    isbn_13 = data.get("isbn_13", [])
    isbn_10 = data.get("isbn_10", [])
    isbn = isbn_13[0] if isbn_13 else (isbn_10[0] if isbn_10 else None)

    languages = data.get("languages", [])
    language = None
    if languages:
        lang_key = languages[0].get("key", "")
        language = lang_key.rsplit("/", 1)[-1] if "/" in lang_key else lang_key

    identifiers: dict[str, str] = {}
    works = data.get("works", [])
    if works:
        identifiers["openlibrary_work"] = works[0]["key"]

    return BookMetadata(
        title=title,
        publisher=publisher,
        isbn=isbn,
        language=language,
        identifiers=identifiers,
    )


def parse_works_response(data: dict[str, Any]) -> str | None:
    """Extract the description from an Open Library Works response.

    Handles the OL quirk where description can be either a plain string
    or a dict with {"type": ..., "value": "actual text"}.
    """
    desc = data.get("description")
    if desc is None:
        return None
    if isinstance(desc, str):
        return desc
    if isinstance(desc, dict):
        return desc.get("value")
    return None


def parse_works_metadata(data: dict[str, Any]) -> BookMetadata:
    """Parse an Open Library Works endpoint response into BookMetadata.

    Extracts title, description, works key, and author keys from the works
    response. Author keys are stored in identifiers for later resolution
    via the author endpoint.
    """
    title = data.get("title", "Unknown")
    description = parse_works_response(data)

    identifiers: dict[str, str] = {}
    works_key = data.get("key")
    if works_key:
        identifiers["openlibrary_work"] = works_key

    # Works responses store authors as [{author: {key: "/authors/..."}}]
    author_entries = data.get("authors", [])
    author_keys = []
    for entry in author_entries:
        author_ref = entry.get("author", {})
        key = author_ref.get("key", "")
        if key:
            author_keys.append(key)
    if author_keys:
        identifiers["openlibrary_author_keys"] = ",".join(author_keys)

    return BookMetadata(
        title=title,
        description=description,
        identifiers=identifiers,
    )


def parse_author_name(data: dict[str, Any]) -> str:
    """Extract the author name from an Open Library Author response."""
    return data.get("name", "Unknown")


def parse_search_results(data: dict[str, Any]) -> list[BookMetadata]:
    """Parse an Open Library Search API response into a list of BookMetadata.

    Each doc in the search results contains title, author_name, isbn, etc.
    """
    docs = data.get("docs", [])
    results: list[BookMetadata] = []

    for doc in docs:
        title = doc.get("title", "Unknown")
        authors = doc.get("author_name", [])
        isbns = doc.get("isbn", [])
        isbn = isbns[0] if isbns else None

        languages = doc.get("language", [])
        language = languages[0] if languages else None

        publishers = doc.get("publisher", [])
        publisher = publishers[0] if publishers else None

        identifiers: dict[str, str] = {}
        work_key = doc.get("key")
        if work_key:
            identifiers["openlibrary_work"] = work_key

        results.append(
            BookMetadata(
                title=title,
                authors=authors,
                isbn=isbn,
                language=language,
                publisher=publisher,
                identifiers=identifiers,
            )
        )

    return results


# Format preference for edition selection (lower = better).
_FORMAT_RANK: dict[str, int] = {
    "hardcover": 0,
    "paperback": 1,
    "trade paperback": 1,
    "mass market paperback": 1,
    "electronic resource": 2,
    "ebook": 2,
    "audio cd": 3,
    "audio cassette": 3,
}
_FORMAT_RANK_DEFAULT = 2


def select_best_edition(entries: list[dict[str, Any]]) -> dict[str, str | None] | None:
    """Pick the best edition from a list of Open Library edition entries.

    Prefers physical formats with ISBNs. Returns a dict with 'isbn' and
    'publisher' keys, or None if no usable edition was found.
    """
    scored: list[tuple[int, int, dict[str, str | None]]] = []

    for entry in entries:
        isbn_13 = entry.get("isbn_13", [])
        isbn_10 = entry.get("isbn_10", [])
        isbn = isbn_13[0] if isbn_13 else (isbn_10[0] if isbn_10 else None)
        if not isbn:
            continue

        publishers = entry.get("publishers", [])
        publisher = publishers[0] if publishers else None

        fmt = (entry.get("physical_format") or "").lower()
        format_rank = _FORMAT_RANK.get(fmt, _FORMAT_RANK_DEFAULT)
        # Prefer ISBN-13 (0) over ISBN-10 only (1)
        isbn_rank = 0 if isbn_13 else 1

        scored.append((format_rank, isbn_rank, {"isbn": isbn, "publisher": publisher}))

    if not scored:
        return None

    scored.sort(key=lambda pair: (pair[0], pair[1]))
    return scored[0][2]


def build_cover_url(isbn: str, size: str = "L") -> str:
    """Build an Open Library cover image URL for a given ISBN.

    Args:
        isbn: The ISBN to look up cover art for.
        size: Image size — "S" (small), "M" (medium), or "L" (large).
    """
    return f"{_COVERS_BASE_URL}/{isbn}-{size}.jpg"
