# ABOUTME: Deduplication logic for filtering redundant files and normalizing metadata.
# ABOUTME: Handles MOBI co-location filtering, title/author/ISBN normalization for dedup matching.

import re
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


# Leading articles to strip from titles for dedup comparison
_LEADING_ARTICLES = re.compile(r"^(the|a|an)\s+", re.IGNORECASE)


def normalize_for_dedup(title: str) -> str:
    """Normalize a book title for duplicate comparison.

    Lowercases, collapses whitespace, and strips leading articles
    (the, a, an).
    """
    if not title:
        return ""
    text = " ".join(title.lower().split())
    text = _LEADING_ARTICLES.sub("", text)
    return text.strip()


def normalize_author_for_dedup(author: str) -> str:
    """Normalize an author name to 'last, first' form, lowercased.

    Handles both 'First Last' and 'Last, First' input formats.
    Single-name authors (e.g. 'Voltaire') are returned lowercased as-is.
    """
    if not author:
        return ""
    name = " ".join(author.lower().split())

    # Already in "last, first" form
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        return f"{parts[0]}, {parts[1]}"

    # "First Last" → "Last, First"
    parts = name.rsplit(None, 1)
    if len(parts) == 1:
        return parts[0]
    return f"{parts[1]}, {parts[0]}"


def normalize_isbn(isbn: str | None) -> str:
    """Normalize an ISBN: strip hyphens/spaces, convert ISBN-10 to ISBN-13.

    Returns an empty string for None or empty input.
    """
    if not isbn:
        return ""
    cleaned = re.sub(r"[\s-]", "", isbn)
    if not cleaned:
        return ""

    if len(cleaned) == 10:
        if not cleaned[:9].isdigit():
            return cleaned
        cleaned = isbn10_to_isbn13(cleaned)

    return cleaned


def isbn10_to_isbn13(isbn10: str) -> str:
    """Convert an ISBN-10 to ISBN-13 by prepending 978 and recalculating the check digit.

    Input must be 10 characters of stripped (no hyphen/space) ISBN-10 with the
    first 9 characters numeric; the 10th may be 'X'. Returns a 13-digit ISBN-13.
    """
    if len(isbn10) != 10 or not isbn10[:9].isdigit():
        raise ValueError(f"Not a valid ISBN-10: {isbn10!r}")
    base = "978" + isbn10[:9]
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(base))
    check = (10 - (total % 10)) % 10
    return base + str(check)


def isbn13_to_isbn10(isbn13: str) -> str:
    """Convert an ISBN-13 (978 prefix) to ISBN-10 by recalculating the mod-11 check digit.

    Only the 978 prefix can round-trip to ISBN-10; a 979 prefix has no ISBN-10
    equivalent and raises ValueError. Check digit 10 is encoded as 'X'.
    """
    if len(isbn13) != 13 or not isbn13.isdigit():
        raise ValueError(f"Not a valid ISBN-13: {isbn13!r}")
    if not isbn13.startswith("978"):
        raise ValueError(f"ISBN-13 with non-978 prefix has no ISBN-10: {isbn13!r}")
    body = isbn13[3:12]
    total = sum(int(d) * (10 - i) for i, d in enumerate(body))
    remainder = total % 11
    check_num = (11 - remainder) % 11
    check = "X" if check_num == 10 else str(check_num)
    return body + check
