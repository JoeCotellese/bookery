# ABOUTME: Detects source book format (epub / kindle / pdf) by suffix + magic bytes.
# ABOUTME: Used by add and import commands to route non-EPUB inputs through converters.

from pathlib import Path
from typing import Literal

SourceFormat = Literal["epub", "mobi", "pdf"]

# Kindle containers that KindleUnpack reads; all route through the MOBI pipeline.
KINDLE_SUFFIXES = frozenset({".mobi", ".azw", ".azw3"})


class UnknownFormatError(ValueError):
    """Raised when a file's extension and magic bytes don't match a supported format."""


def detect_source_format(path: Path) -> SourceFormat:
    """Return the file's format based on suffix + small magic-byte sanity check."""
    suffix = path.suffix.lower()
    if suffix == ".epub":
        return "epub"
    if suffix in KINDLE_SUFFIXES:
        return "mobi"
    if suffix == ".pdf":
        try:
            with path.open("rb") as fh:
                head = fh.read(5)
        except OSError as exc:
            raise UnknownFormatError(f"cannot read {path}: {exc}") from exc
        if not head.startswith(b"%PDF-"):
            raise UnknownFormatError(f"{path.name} has a .pdf suffix but is not a PDF file.")
        return "pdf"
    raise UnknownFormatError(
        f"{path.name}: unsupported format (expected .epub, .mobi, .azw, .azw3, or .pdf)."
    )


def find_kindle_files(directory: Path) -> list[Path]:
    """Recursively find Kindle files (any suffix case) under a directory."""
    return sorted(
        p for p in directory.rglob("*") if p.is_file() and p.suffix.lower() in KINDLE_SUFFIXES
    )
