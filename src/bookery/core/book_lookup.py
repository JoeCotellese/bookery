# ABOUTME: Resolve a user-supplied book reference (ID or title) to a BookRecord.
# ABOUTME: Returns a typed result union: Found, NotFound, Ambiguous, or Suggestions.

from __future__ import annotations

from dataclasses import dataclass
from difflib import get_close_matches
from typing import Protocol

from bookery.db.mapping import BookRecord


class CatalogLike(Protocol):
    def get_by_id(self, book_id: int) -> BookRecord | None: ...
    def list_all(self) -> list[BookRecord]: ...


@dataclass(frozen=True)
class Found:
    record: BookRecord


@dataclass(frozen=True)
class NotFound:
    pass


@dataclass(frozen=True)
class Ambiguous:
    records: list[BookRecord]


@dataclass(frozen=True)
class Suggestions:
    records: list[BookRecord]


LookupResult = Found | NotFound | Ambiguous | Suggestions


def resolve_book(catalog: CatalogLike, query: str) -> LookupResult:
    """Resolve ``query`` to a single book, multiple matches, or suggestions.

    Resolution order:
    1. If ``query`` is purely numeric, look up by ID.
    2. Otherwise scan titles for case-insensitive substring matches.
    3. If no substring matches, fall back to fuzzy matching with difflib.
    """
    query = query.strip()
    if not query:
        return NotFound()

    if query.isdigit():
        record = catalog.get_by_id(int(query))
        return Found(record) if record else NotFound()

    needle = query.lower()
    all_records = catalog.list_all()
    matches = [r for r in all_records if needle in r.metadata.title.lower()]

    if len(matches) == 1:
        return Found(matches[0])
    if len(matches) > 1:
        return Ambiguous(matches)

    # Fuzzy fallback against titles.
    titles = [r.metadata.title for r in all_records]
    close = get_close_matches(query, titles, n=5, cutoff=0.6)
    if close:
        suggested = [r for r in all_records if r.metadata.title in close]
        return Suggestions(suggested)

    return NotFound()
