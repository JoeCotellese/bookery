# ABOUTME: Non-destructive metadata write pipeline.
# ABOUTME: Copies EPUB to output directory then writes updated metadata to the copy.

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from bookery.formats.epub import EpubReadError, read_epub_metadata, write_epub_metadata
from bookery.metadata.types import BookMetadata


@dataclass
class FieldVerification:
    """Result of verifying a single metadata field after write-back."""

    field: str
    expected: str | None
    actual: str | None
    passed: bool


@dataclass
class WriteResult:
    """Result of a metadata write operation with verification status."""

    path: Path | None
    success: bool
    verified_fields: list[FieldVerification] = field(default_factory=list)
    error: str | None = None


_MAX_COLLISION_ATTEMPTS = 10_000


def _resolve_collision(output_path: Path) -> Path:
    """Find a non-colliding filename by appending _1, _2, etc."""
    stem = output_path.stem
    suffix = output_path.suffix
    parent = output_path.parent
    for counter in range(1, _MAX_COLLISION_ATTEMPTS + 1):
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
    raise OSError(
        f"Could not find a non-colliding filename after "
        f"{_MAX_COLLISION_ATTEMPTS} attempts: {output_path}"
    )


def _verify_write(dest: Path, metadata: BookMetadata) -> list[FieldVerification]:
    """Read back the EPUB at dest and compare fields against metadata.

    Only verifies fields that are non-None in metadata. Authors are compared
    as sorted lists. Language comparison is case-insensitive.
    """
    read_back = read_epub_metadata(dest)
    verifications: list[FieldVerification] = []

    # Title — always verified (title is never None)
    verifications.append(FieldVerification(
        field="title",
        expected=metadata.title,
        actual=read_back.title,
        passed=metadata.title == read_back.title,
    ))

    # Authors — sorted comparison for order independence
    if metadata.authors:
        expected_sorted = ", ".join(sorted(metadata.authors))
        actual_sorted = ", ".join(sorted(read_back.authors))
        verifications.append(FieldVerification(
            field="authors",
            expected=expected_sorted,
            actual=actual_sorted,
            passed=expected_sorted == actual_sorted,
        ))

    # Language — case-insensitive
    if metadata.language is not None:
        actual_lang = read_back.language
        passed = (
            actual_lang is not None
            and metadata.language.lower() == actual_lang.lower()
        )
        verifications.append(FieldVerification(
            field="language",
            expected=metadata.language,
            actual=actual_lang,
            passed=passed,
        ))

    # Publisher — exact match
    if metadata.publisher is not None:
        verifications.append(FieldVerification(
            field="publisher",
            expected=metadata.publisher,
            actual=read_back.publisher,
            passed=metadata.publisher == read_back.publisher,
        ))

    # Description — exact match
    if metadata.description is not None:
        verifications.append(FieldVerification(
            field="description",
            expected=metadata.description,
            actual=read_back.description,
            passed=metadata.description == read_back.description,
        ))

    return verifications


def _cleanup_dest(dest: Path) -> None:
    """Remove the destination file if it exists."""
    if dest.exists():
        dest.unlink()


def apply_metadata_safely(
    source: Path, metadata: BookMetadata, output_dir: Path
) -> WriteResult:
    """Copy an EPUB to output_dir and write updated metadata to the copy.

    The original file is never modified. If a file with the same name already
    exists in output_dir, a numeric suffix (_1, _2, ...) is appended.
    After writing, the copy is read back and verified field-by-field.
    If write or verification fails, the copy is deleted.

    Args:
        source: Path to the original EPUB file.
        metadata: BookMetadata to write to the copy.
        output_dir: Directory to place the modified copy.

    Returns:
        WriteResult with path, success flag, and verification details.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    dest = output_dir / source.name
    if dest.exists():
        dest = _resolve_collision(dest)

    shutil.copy2(source, dest)

    # Write metadata to the copy
    try:
        write_epub_metadata(dest, metadata)
    except (OSError, EpubReadError) as exc:
        _cleanup_dest(dest)
        return WriteResult(path=None, success=False, error=str(exc))

    # Verify the write by reading back
    try:
        verifications = _verify_write(dest, metadata)
    except (OSError, EpubReadError) as exc:
        _cleanup_dest(dest)
        return WriteResult(path=None, success=False, error=str(exc))

    # Check if all fields passed
    if not all(v.passed for v in verifications):
        _cleanup_dest(dest)
        failed = [v.field for v in verifications if not v.passed]
        return WriteResult(
            path=None,
            success=False,
            verified_fields=verifications,
            error=f"Verification failed for: {', '.join(failed)}",
        )

    return WriteResult(path=dest, success=True, verified_fields=verifications)
