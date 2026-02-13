# ABOUTME: Directory scanner for ebook format inventory.
# ABOUTME: Walks a directory tree, identifies ebook files, and reports format coverage.

from dataclasses import dataclass, field
from pathlib import Path

EBOOK_EXTENSIONS: frozenset[str] = frozenset(
    {".epub", ".mobi", ".azw3", ".azw", ".pdf", ".txt", ".cbz", ".cbr"}
)


@dataclass
class BookEntry:
    """A single book directory with its detected formats."""

    directory: Path
    author: str | None
    title: str | None
    formats: set[str] = field(default_factory=set)

    @property
    def name(self) -> str:
        """Human-readable name: 'Title - Author' or directory name fallback."""
        if self.title and self.author:
            return f"{self.title} - {self.author}"
        if self.title:
            return self.title
        return self.directory.name

    def has_format(self, ext: str) -> bool:
        """Check if this book has a given format. Normalizes dot prefix and case."""
        normalized = ext.lower() if ext.startswith(".") else f".{ext.lower()}"
        return normalized in self.formats


@dataclass
class ScanResult:
    """Aggregated results from scanning a directory tree for ebooks."""

    books: list[BookEntry]
    format_counts: dict[str, int]
    scan_root: Path

    @property
    def total_books(self) -> int:
        """Total number of book directories found."""
        return len(self.books)

    def missing_format(self, ext: str) -> list[BookEntry]:
        """Return books that do not have the given format."""
        return [book for book in self.books if not book.has_format(ext)]
