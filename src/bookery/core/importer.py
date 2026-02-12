# ABOUTME: Import pipeline for cataloging EPUBs into the Bookery library database.
# ABOUTME: Extracts metadata, computes file hashes, and stores records in the catalog.

from dataclasses import dataclass, field
from pathlib import Path

from bookery.db.catalog import DuplicateBookError, LibraryCatalog
from bookery.db.hashing import compute_file_hash
from bookery.formats.epub import EpubReadError, read_epub_metadata


@dataclass
class ImportResult:
    """Summary of an import operation."""

    added: int = 0
    skipped: int = 0
    errors: int = 0
    error_details: list[tuple[Path, str]] = field(default_factory=list)


def import_books(
    paths: list[Path],
    catalog: LibraryCatalog,
) -> ImportResult:
    """Import EPUB files into the library catalog.

    For each file: extracts metadata, computes SHA-256 hash, and adds to
    the catalog. Duplicate files (same hash) are skipped. Corrupt files
    are recorded as errors.

    Args:
        paths: List of EPUB file paths to import.
        catalog: The library catalog to add books to.

    Returns:
        ImportResult with counts of added, skipped, and errored files.
    """
    result = ImportResult()

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

        try:
            catalog.add_book(metadata, file_hash=file_hash)
            result.added += 1
        except DuplicateBookError:
            # Race condition guard — another process could have inserted
            result.skipped += 1

    return result
