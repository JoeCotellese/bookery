# ABOUTME: Directory scanner for ebook format inventory.
# ABOUTME: Walks a directory tree, identifies ebook files, and reports format coverage.

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bookery.db.catalog import LibraryCatalog

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


# Matches a trailing parenthesized Calibre ID like " (2739)" at end of string
_CALIBRE_ID_RE = re.compile(r"\s+\(\d+\)$")


def _parse_calibre_dir(
    book_dir: Path, scan_root: Path | None = None
) -> tuple[str | None, str | None]:
    """Extract author and title from a Calibre-style directory path.

    Calibre layout: Author Name/Book Title (calibre_id)/
    Strips trailing (digits) calibre ID from the directory name.
    Author is inferred from the grandparent directory when the book dir
    is at least two levels deep under scan_root.

    Returns:
        (author, title) tuple. Author is None if book_dir is directly
        under scan_root (or has no meaningful grandparent).
    """
    dirname = book_dir.name
    title = _CALIBRE_ID_RE.sub("", dirname) or dirname

    # Author from parent: /scan_root/Author/Title (id)/
    parent = book_dir.parent
    if scan_root is not None:
        author = parent.name if parent != scan_root else None
    else:
        grandparent = parent.parent
        author = parent.name if grandparent != parent else None

    return author, title


def scan_directory(root: Path) -> ScanResult:
    """Walk a directory tree and group ebook files by leaf directory.

    Each directory containing at least one ebook file is treated as a single
    book. Author and title are inferred from the Calibre-style directory
    layout when possible.

    Args:
        root: The top-level directory to scan.

    Returns:
        A ScanResult with all discovered books and format counts.
    """
    # Collect ebook files grouped by their parent directory
    dir_formats: dict[Path, set[str]] = defaultdict(set)

    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in EBOOK_EXTENSIONS:
            dir_formats[path.parent].add(path.suffix.lower())

    # Build BookEntry for each directory that had ebook files
    books: list[BookEntry] = []
    format_counts: dict[str, int] = defaultdict(int)

    for book_dir in sorted(dir_formats):
        formats = dir_formats[book_dir]
        author, title = _parse_calibre_dir(book_dir, scan_root=root)

        books.append(
            BookEntry(
                directory=book_dir,
                author=author,
                title=title,
                formats=formats,
            )
        )

        for fmt in formats:
            format_counts[fmt] += 1

    return ScanResult(
        books=books,
        format_counts=dict(format_counts),
        scan_root=root,
    )


@dataclass
class DbCrossReference:
    """Result of matching scan entries against the library catalog."""

    in_catalog: list[BookEntry]
    not_in_catalog: list[BookEntry]


def cross_reference_db(
    scan_result: ScanResult, catalog: LibraryCatalog
) -> DbCrossReference:
    """Match scanned books against the catalog by source_path.

    A book is considered "in catalog" if any file in its directory matches
    a cataloged source_path.

    Args:
        scan_result: The scan result to cross-reference.
        catalog: The library catalog to match against.

    Returns:
        A DbCrossReference with books split into cataloged and uncataloged.
    """
    cataloged_paths: set[Path] = {
        record.source_path for record in catalog.list_all()
    }

    in_catalog: list[BookEntry] = []
    not_in_catalog: list[BookEntry] = []

    for book in scan_result.books:
        # Check if any ebook file in this directory is cataloged
        book_files = {
            f
            for f in book.directory.iterdir()
            if f.is_file() and f.suffix.lower() in EBOOK_EXTENSIONS
        }
        if book_files & cataloged_paths:
            in_catalog.append(book)
        else:
            not_in_catalog.append(book)

    return DbCrossReference(in_catalog=in_catalog, not_in_catalog=not_in_catalog)
