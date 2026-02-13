# ABOUTME: Import pipeline for cataloging EPUBs into the Bookery library database.
# ABOUTME: Extracts metadata, computes file hashes, and stores records in the catalog.

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from bookery.db.catalog import DuplicateBookError, LibraryCatalog
from bookery.db.hashing import compute_file_hash
from bookery.formats.epub import EpubReadError, read_epub_metadata
from bookery.metadata.types import BookMetadata


@dataclass
class ImportResult:
    """Summary of an import operation."""

    added: int = 0
    skipped: int = 0
    errors: int = 0
    error_details: list[tuple[Path, str]] = field(default_factory=list)


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


def import_books(
    paths: list[Path],
    catalog: LibraryCatalog,
    *,
    match_fn: MatchFn | None = None,
) -> ImportResult:
    """Import EPUB files into the library catalog.

    For each file: extracts metadata, computes SHA-256 hash, and adds to
    the catalog. Duplicate files (same hash) are skipped. Corrupt files
    are recorded as errors.

    When match_fn is provided, it is called with (extracted_metadata, epub_path)
    after extraction. If it returns a MatchResult, the matched metadata and
    output_path are used for the catalog entry. If it returns None (user
    skipped), the original metadata is cataloged without an output_path.

    Args:
        paths: List of EPUB file paths to import.
        catalog: The library catalog to add books to.
        match_fn: Optional callback to run the match pipeline per file.

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
            continue

        # Check for duplicate before reading metadata (cheaper)
        if catalog.get_by_hash(file_hash) is not None:
            result.skipped += 1
            continue

        try:
            metadata = read_epub_metadata(epub_path)
        except EpubReadError as exc:
            result.errors += 1
            result.error_details.append((epub_path, str(exc)))
            continue

        metadata.source_path = epub_path

        output_path: Path | None = None

        if match_fn is not None:
            match_result = match_fn(metadata, epub_path)
            if match_result is not None:
                metadata = match_result.metadata
                metadata.source_path = epub_path
                output_path = match_result.output_path

        try:
            catalog.add_book(
                metadata, file_hash=file_hash, output_path=output_path,
            )
            result.added += 1
        except DuplicateBookError:
            # Race condition guard — another process could have inserted
            result.skipped += 1

    return result
