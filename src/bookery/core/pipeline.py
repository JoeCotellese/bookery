# ABOUTME: Non-destructive metadata write pipeline.
# ABOUTME: Copies EPUB to output directory then writes updated metadata to the copy.

import shutil
from pathlib import Path

from bookery.formats.epub import write_epub_metadata
from bookery.metadata.types import BookMetadata


def _resolve_collision(output_path: Path) -> Path:
    """Find a non-colliding filename by appending _1, _2, etc."""
    stem = output_path.stem
    suffix = output_path.suffix
    parent = output_path.parent
    counter = 1
    while output_path.exists():
        output_path = parent / f"{stem}_{counter}{suffix}"
        counter += 1
    return output_path


def apply_metadata_safely(
    source: Path, metadata: BookMetadata, output_dir: Path
) -> Path:
    """Copy an EPUB to output_dir and write updated metadata to the copy.

    The original file is never modified. If a file with the same name already
    exists in output_dir, a numeric suffix (_1, _2, ...) is appended.

    Args:
        source: Path to the original EPUB file.
        metadata: BookMetadata to write to the copy.
        output_dir: Directory to place the modified copy.

    Returns:
        Path to the modified copy.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    dest = output_dir / source.name
    if dest.exists():
        dest = _resolve_collision(dest)

    shutil.copy2(source, dest)
    write_epub_metadata(dest, metadata)
    return dest
