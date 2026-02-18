# ABOUTME: Batch genre assignment for books already in the catalog.
# ABOUTME: Runs normalize_subjects() across cataloged books and assigns genres.

from dataclasses import dataclass, field

from bookery.db.catalog import LibraryCatalog
from bookery.metadata.genres import normalize_subjects


@dataclass
class ApplyResult:
    """Summary of a batch genre-apply operation."""

    assigned: list[tuple[int, str, str]] = field(default_factory=list)
    unmatched: list[tuple[int, str, list[str]]] = field(default_factory=list)


def apply_genres(
    catalog: LibraryCatalog,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> ApplyResult:
    """Apply genre normalization to cataloged books.

    Runs normalize_subjects() on each book's subjects and assigns the
    resulting genres. Uses the same assignment pattern as the importer.

    Args:
        catalog: The library catalog to operate on.
        dry_run: If True, report what would happen without writing.
        force: If True, re-evaluate all books with subjects (not just ungenred).

    Returns:
        ApplyResult with counts of assigned, skipped, and unmatched books.
    """
    result = ApplyResult()

    books = catalog.get_books_with_subjects() if force else catalog.get_unmatched_subjects()

    for book_id, title, subjects in books:
        genre_result = normalize_subjects(subjects)

        if not genre_result.matches:
            result.unmatched.append((book_id, title, subjects))
            continue

        primary_genre = genre_result.primary_genre or genre_result.matches[0].genre
        result.assigned.append((book_id, title, primary_genre))

        if not dry_run:
            for match in genre_result.matches:
                catalog.add_genre(book_id, match.genre)
            if genre_result.primary_genre:
                catalog.set_primary_genre(book_id, genre_result.primary_genre)

    return result
