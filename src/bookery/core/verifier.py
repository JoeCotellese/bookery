# ABOUTME: Library integrity verification for the Bookery catalog.
# ABOUTME: Checks that cataloged files exist on disk and optionally validates hashes.

from dataclasses import dataclass, field

from bookery.db.catalog import LibraryCatalog
from bookery.db.hashing import compute_file_hash
from bookery.db.mapping import BookRecord


@dataclass
class VerifyResult:
    """Aggregated results from a library verification run."""

    ok: int = 0
    missing_source: list[BookRecord] = field(default_factory=list)
    missing_output: list[BookRecord] = field(default_factory=list)
    hash_mismatch: list[BookRecord] = field(default_factory=list)

    @property
    def total_issues(self) -> int:
        """Total number of issues found across all categories."""
        return len(self.missing_source) + len(self.missing_output) + len(self.hash_mismatch)


def verify_library(catalog: LibraryCatalog, *, check_hash: bool = False) -> VerifyResult:
    """Verify integrity of all books in the catalog.

    For each cataloged book:
    1. Check source_path exists on disk.
    2. Check output_path exists on disk (if set).
    3. If check_hash is True and source exists, re-hash and compare.

    Args:
        catalog: The library catalog to verify.
        check_hash: Whether to recompute and compare file hashes.

    Returns:
        A VerifyResult with counts and lists of problematic records.
    """
    result = VerifyResult()

    for record in catalog.list_all():
        has_issue = False

        # Check source file
        source_exists = record.source_path.exists()
        if not source_exists:
            result.missing_source.append(record)
            has_issue = True

        # Check output file (only if output_path is set)
        if record.output_path is not None and not record.output_path.exists():
            result.missing_output.append(record)
            has_issue = True

        # Check hash (only if requested and source exists)
        if check_hash and source_exists:
            current_hash = compute_file_hash(record.source_path)
            if current_hash != record.file_hash:
                result.hash_mismatch.append(record)
                has_issue = True

        if not has_issue:
            result.ok += 1

    return result
