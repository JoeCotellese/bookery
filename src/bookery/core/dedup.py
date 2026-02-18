# ABOUTME: Deduplication logic for filtering redundant MOBI files.
# ABOUTME: Skips MOBIs when an EPUB already exists in the same directory.

from pathlib import Path


def filter_redundant_mobis(
    mobi_files: list[Path],
    epub_files: list[Path],
) -> tuple[list[Path], list[Path]]:
    """Partition MOBIs into (to_convert, skipped) based on EPUB presence.

    A MOBI is considered redundant if its parent directory already contains
    an EPUB file (Calibre convention: one book per directory).
    """
    epub_dirs: set[Path] = {epub.parent for epub in epub_files}

    to_convert: list[Path] = []
    skipped: list[Path] = []

    for mobi in mobi_files:
        if mobi.parent in epub_dirs:
            skipped.append(mobi)
        else:
            to_convert.append(mobi)

    return to_convert, skipped
