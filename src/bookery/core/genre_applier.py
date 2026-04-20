# ABOUTME: Batch genre assignment for books already in the catalog.
# ABOUTME: Runs normalize_subjects() across cataloged books and assigns genres.

from collections import Counter
from dataclasses import dataclass, field

from bookery.db.catalog import LibraryCatalog
from bookery.metadata.genres import normalize_subject, normalize_subjects

AUTO_SOURCE = "genres"
PRIMARY_GENRE_FIELD = "genre_primary"


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


def auto_apply_for_book(
    catalog: LibraryCatalog,
    book_id: int,
    subjects: list[str],
) -> str | None:
    """Assign genres for a single book from its subjects.

    Runs the same normalization as ``apply_genres`` but for one book,
    used as a hook after ``catalog.update_book`` writes fresh subjects.
    Respects a locked ``genre_primary`` provenance row: when locked, the
    primary genre is preserved even if a different genre would normally
    win the vote. Non-primary genre memberships are still refreshed.

    Returns the resolved primary genre name (or None if no matches).
    """
    if not subjects:
        return None

    result = normalize_subjects(subjects)
    if not result.matches:
        return None

    # Honor a user-set lock on the primary genre.
    provenance = catalog.get_provenance(book_id)
    locked = provenance.get(PRIMARY_GENRE_FIELD)
    primary_locked = bool(locked and locked.locked)

    for match in result.matches:
        catalog.add_genre(book_id, match.genre)

    primary = result.primary_genre
    if primary and not primary_locked:
        catalog.set_primary_genre(book_id, primary)
        # Record provenance for the primary so future locks can protect it.
        catalog._upsert_provenance(book_id, PRIMARY_GENRE_FIELD, AUTO_SOURCE)
        catalog._conn.commit()
        return primary

    if primary_locked:
        existing = catalog.get_primary_genre(book_id)
        return existing
    return primary


def collect_unmatched_subject_frequencies(
    catalog: LibraryCatalog,
) -> list[tuple[str, int]]:
    """Return (subject, count) tuples for subjects that don't map to a genre.

    Aggregates across the catalog and sorts by descending frequency.
    Useful for ``bookery genre stats`` to surface mappings worth adding.
    """
    counts: Counter[str] = Counter()
    for _book_id, _title, subjects in catalog.get_books_with_subjects():
        for subj in subjects:
            if normalize_subject(subj) is None:
                counts[subj] += 1
    return counts.most_common()
