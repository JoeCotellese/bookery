# ABOUTME: Core metadata data structures for ebook metadata representation.
# ABOUTME: BookMetadata is the interchange format between extraction, matching, and writing.

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BookMetadata:
    """Structured metadata for an ebook file.

    This is the central data structure that flows through the metadata pipeline:
    extraction -> matching -> review -> writing. All fields are optional except
    title, since even a badly-formed EPUB should have something we can call a title.
    """

    title: str
    authors: list[str] = field(default_factory=list)
    author_sort: str | None = None
    language: str | None = None
    publisher: str | None = None
    isbn: str | None = None
    description: str | None = None
    series: str | None = None
    series_index: float | None = None
    identifiers: dict[str, str] = field(default_factory=dict)
    cover_image: bytes | None = None
    source_path: Path | None = None

    @property
    def author(self) -> str:
        """Convenience property: joined author string for display."""
        return ", ".join(self.authors) if self.authors else ""

    @property
    def has_cover(self) -> bool:
        """Whether cover image data is present."""
        return self.cover_image is not None and len(self.cover_image) > 0
