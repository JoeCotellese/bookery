# ABOUTME: Multi-provider enrichment search helpers used by the web UI.
# ABOUTME: Dispatches a single query to every active MetadataProvider and groups results.

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.provider import MetadataProvider


@dataclass(frozen=True)
class ProviderResult:
    """Grouped candidates from a single MetadataProvider.

    ``candidates`` is pre-sorted by confidence descending so templates can
    render directly without further ordering work.
    """

    name: str
    candidates: list[MetadataCandidate]

    @property
    def count(self) -> int:
        return len(self.candidates)

    @property
    def is_empty(self) -> bool:
        return not self.candidates


# Matches a 10- or 13-character ISBN-like token (digits, optional final X for ISBN-10).
_ISBN_RE = re.compile(r"^\d{9}[\dXx]$|^\d{13}$")

# Detect anything that looks like a URL — http(s):// or bare domain prefix.
_URL_RE = re.compile(r"^(?:https?://|www\.)", re.IGNORECASE)


def looks_like_isbn(value: str) -> bool:
    """Return True if ``value`` looks like a normalized ISBN-10 or ISBN-13.

    Whitespace and hyphens are stripped before testing, so user input such as
    ``978-0-441-17271-9`` still resolves to the ISBN dispatch path.
    """
    stripped = re.sub(r"[\s-]", "", value)
    return bool(_ISBN_RE.match(stripped))


def normalize_isbn(value: str) -> str:
    """Strip whitespace and hyphens from an ISBN-like string."""
    return re.sub(r"[\s-]", "", value)


def looks_like_url(value: str) -> bool:
    """Return True if ``value`` looks like a URL (http/https or www-prefixed)."""
    return bool(_URL_RE.match(value.strip()))


@dataclass(frozen=True)
class QueryDispatch:
    """The parsed shape of an enrich search request.

    Exactly one of the three slots is populated, mirroring the dispatch
    branches in :func:`multi_provider_search`.
    """

    isbn: str | None = None
    url: str | None = None
    title_author: str | None = None

    @property
    def is_empty(self) -> bool:
        return not (self.isbn or self.url or self.title_author)


def dispatch_from_form(isbn_field: str, query_field: str) -> QueryDispatch:
    """Parse raw form fields into a :class:`QueryDispatch`.

    A non-empty ``isbn_field`` always wins. Otherwise the free-text
    ``query_field`` is inspected: ISBN-shaped digits route to the ISBN
    branch (digits/hyphens stripped), anything starting with ``http(s)://``
    or ``www.`` routes to the URL branch, and the remainder is treated
    as a title+author search string.
    """
    isbn_input = (isbn_field or "").strip()
    query = (query_field or "").strip()

    if isbn_input:
        return QueryDispatch(isbn=normalize_isbn(isbn_input))
    if not query:
        return QueryDispatch()
    if looks_like_isbn(query):
        return QueryDispatch(isbn=normalize_isbn(query))
    if looks_like_url(query):
        return QueryDispatch(url=query)
    return QueryDispatch(title_author=query)


def multi_provider_search(
    providers: Mapping[str, MetadataProvider],
    *,
    isbn: str | None = None,
    url: str | None = None,
    title_author: str | None = None,
) -> list[ProviderResult]:
    """Fan a single query out across every registered provider.

    Exactly one of ``isbn``, ``url``, or ``title_author`` should be provided.
    For each provider, the matching method is called and results are wrapped
    in a :class:`ProviderResult` ordered by confidence descending. URL lookups
    return at most one candidate per provider.

    Provider iteration order matches ``providers`` insertion order so the UI
    layout is deterministic.
    """
    results: list[ProviderResult] = []
    for _key, provider in providers.items():
        candidates: list[MetadataCandidate] = []
        if isbn:
            candidates = list(provider.search_by_isbn(isbn))
        elif url:
            single = provider.lookup_by_url(url)
            if single is not None:
                candidates = [single]
        elif title_author:
            candidates = list(provider.search_by_title_author(title_author))
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        results.append(ProviderResult(name=provider.name, candidates=candidates))
    return results
