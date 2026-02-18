# ABOUTME: Import pipeline for cataloging EPUBs into the Bookery library database.
# ABOUTME: Extracts metadata, computes file hashes, and stores records in the catalog.

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from bookery.db.catalog import DuplicateBookError, LibraryCatalog
from bookery.db.hashing import compute_file_hash
from bookery.formats.epub import EpubReadError, read_epub_metadata
from bookery.metadata.genres import normalize_subjects
from bookery.metadata.types import BookMetadata


@dataclass
class SkipDetail:
    """Detail about a single skipped file during import."""

    path: Path
    reason: str  # "hash" | "isbn" | "title_author"
    existing_id: int | None = None


@dataclass
class ImportResult:
    """Summary of an import operation."""

    added: int = 0
    skipped: int = 0
    skipped_hash: int = 0
    skipped_metadata: int = 0
    forced: int = 0
    errors: int = 0
    error_details: list[tuple[Path, str]] = field(default_factory=list)
    skip_details: list[SkipDetail] = field(default_factory=list)


@dataclass
class MatchResult:
    """Result of running the match pipeline on a single EPUB.

    Returned by a match_fn callback to provide matched metadata and
    the path to the corrected output copy (if any).
    """

    metadata: BookMetadata
    output_path: Path | None = None


# Type for the match callback: takes (extracted_metadata, epub_path) -> MatchResult or None
MatchFn = Callable[[BookMetadata, Path], MatchResult | None]

# Type for progress callback: fires per-file with status info
# Args: (path, title, author, status, reason, existing_id)
# status is one of: "added", "skipped", "forced", "error"
ProgressFn = Callable[[Path, str, str, str, str | None, int | None], None]


def import_books(
    paths: list[Path],
    catalog: LibraryCatalog,
    *,
    match_fn: MatchFn | None = None,
    force_duplicates: bool = False,
    on_progress: ProgressFn | None = None,
) -> ImportResult:
    """Import EPUB files into the library catalog.

    For each file: extracts metadata, computes SHA-256 hash, and adds to
    the catalog. Duplicate files (same hash) are skipped. Metadata-level
    duplicates (same ISBN or same title+author) are also skipped unless
    force_duplicates is True.

    When match_fn is provided, it is called with (extracted_metadata, epub_path)
    after extraction. If it returns a MatchResult, the matched metadata and
    output_path are used for the catalog entry. If it returns None (user
    skipped), the original metadata is cataloged without an output_path.

    Args:
        paths: List of EPUB file paths to import.
        catalog: The library catalog to add books to.
        match_fn: Optional callback to run the match pipeline per file.
        force_duplicates: If True, import metadata duplicates with a warning.
        on_progress: Optional callback fired per-file with status info.

    Returns:
        ImportResult with counts of added, skipped, and errored files.
    """
    result = ImportResult()

    # TODO: add progress counters [i/N] for batch import feedback
    for epub_path in paths:
        try:
            file_hash = compute_file_hash(epub_path)
        except (OSError, FileNotFoundError) as exc:
            result.errors += 1
            result.error_details.append((epub_path, str(exc)))
            if on_progress:
                on_progress(epub_path, "", "", "error", str(exc), None)
            continue

        # Check for duplicate before reading metadata (cheaper)
        if catalog.get_by_hash(file_hash) is not None:
            result.skipped += 1
            result.skipped_hash += 1
            result.skip_details.append(
                SkipDetail(path=epub_path, reason="hash"),
            )
            if on_progress:
                on_progress(epub_path, "", "", "skipped", "hash", None)
            continue

        try:
            metadata = read_epub_metadata(epub_path)
        except EpubReadError as exc:
            result.errors += 1
            result.error_details.append((epub_path, str(exc)))
            if on_progress:
                on_progress(epub_path, "", "", "error", str(exc), None)
            continue

        metadata.source_path = epub_path

        output_path: Path | None = None

        if match_fn is not None:
            match_result = match_fn(metadata, epub_path)
            if match_result is not None:
                metadata = match_result.metadata
                metadata.source_path = epub_path
                output_path = match_result.output_path

        # Metadata-level duplicate check (ISBN, then title+author)
        dup_match = catalog.find_duplicate(metadata)
        if dup_match is not None:
            existing_id = dup_match.record.id
            result.skip_details.append(
                SkipDetail(
                    path=epub_path,
                    reason=dup_match.reason,
                    existing_id=existing_id,
                ),
            )
            if not force_duplicates:
                result.skipped += 1
                result.skipped_metadata += 1
                if on_progress:
                    on_progress(
                        epub_path, metadata.title, metadata.author,
                        "skipped", dup_match.reason, existing_id,
                    )
                continue
            # force_duplicates: import anyway but track it

        try:
            book_id = catalog.add_book(
                metadata, file_hash=file_hash, output_path=output_path,
            )
            result.added += 1
            if dup_match is not None:
                result.forced += 1
            if on_progress:
                status = "forced" if dup_match else "added"
                on_progress(
                    epub_path, metadata.title, metadata.author,
                    status,
                    dup_match.reason if dup_match else None,
                    dup_match.record.id if dup_match else None,
                )
        except DuplicateBookError:
            # Race condition guard — another process could have inserted
            result.skipped += 1
            result.skipped_hash += 1
            result.skip_details.append(
                SkipDetail(path=epub_path, reason="hash"),
            )
            continue

        # Auto-assign genres from subjects
        if metadata.subjects:
            catalog.store_subjects(book_id, metadata.subjects)
            genre_result = normalize_subjects(metadata.subjects)
            for match in genre_result.matches:
                catalog.add_genre(book_id, match.genre)
            if genre_result.primary_genre:
                catalog.set_primary_genre(book_id, genre_result.primary_genre)

    return result
