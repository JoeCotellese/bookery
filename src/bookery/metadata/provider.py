# ABOUTME: MetadataProvider protocol defining the contract for metadata sources.
# ABOUTME: Any external metadata API (Open Library, Google Books, etc.) implements this.

from typing import Protocol, runtime_checkable

from bookery.metadata.candidate import MetadataCandidate


@runtime_checkable
class MetadataProvider(Protocol):
    """Protocol for metadata lookup services.

    Implementations must provide ISBN-based and title/author-based search,
    returning ranked MetadataCandidate lists.
    """

    @property
    def name(self) -> str: ...

    def search_by_isbn(self, isbn: str) -> list[MetadataCandidate]: ...

    def search_by_title_author(
        self, title: str, author: str | None = None
    ) -> list[MetadataCandidate]: ...

    def lookup_by_url(self, url: str) -> MetadataCandidate | None: ...
