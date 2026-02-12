# ABOUTME: EPUB metadata extraction and writing using ebooklib.
# ABOUTME: Defensive wrapper that handles malformed files gracefully.

import logging
from pathlib import Path

from ebooklib import epub

from bookery.metadata.types import BookMetadata

logger = logging.getLogger(__name__)


class EpubReadError(Exception):
    """Raised when an EPUB file cannot be read or parsed."""


def _get_metadata_value(book: epub.EpubBook, namespace: str, name: str) -> str | None:
    """Extract a single metadata value from an EpubBook, or None if missing."""
    values = book.get_metadata(namespace, name)
    if not values:
        return None
    # Metadata entries are tuples of (value, attributes)
    value = values[0][0]
    return str(value).strip() if value else None


def _get_authors(book: epub.EpubBook) -> list[str]:
    """Extract all author names from an EpubBook."""
    creators = book.get_metadata("DC", "creator")
    if not creators:
        return []
    return [str(entry[0]).strip() for entry in creators if entry[0]]


def _get_identifiers(book: epub.EpubBook) -> dict[str, str]:
    """Extract all identifiers (ISBN, UUID, etc.) from an EpubBook."""
    identifiers = {}
    entries = book.get_metadata("DC", "identifier")
    for value, attrs in entries:
        if not value:
            continue
        scheme = attrs.get("opf:scheme", attrs.get("scheme", "id"))
        identifiers[scheme.lower()] = str(value).strip()
    return identifiers


def _detect_isbn(identifiers: dict[str, str]) -> str | None:
    """Try to find an ISBN among the identifiers."""
    for key in ("isbn", "isbn13", "isbn-13", "isbn10", "isbn-10"):
        if key in identifiers:
            return identifiers[key]
    # Check if any identifier value looks like an ISBN
    for value in identifiers.values():
        cleaned = value.replace("-", "").replace(" ", "")
        if len(cleaned) in (10, 13) and cleaned.replace("X", "").isdigit():
            return value
    return None


def _extract_cover_image(book: epub.EpubBook) -> bytes | None:
    """Extract cover image data from an EPUB, if present."""
    # Check for cover image in metadata
    cover_id = None
    meta_entries = book.get_metadata("OPF", "cover")
    if meta_entries:
        cover_id = meta_entries[0][1].get("content")

    if cover_id:
        cover_item = book.get_item_with_id(cover_id)
        if cover_item:
            return cover_item.get_content()

    # Fallback: look for items with "cover" in the id or filename
    for item in book.get_items():
        item_id = item.get_id() or ""
        item_name = item.get_name() or ""
        if "cover" in item_id.lower() or "cover" in item_name.lower():
            content_type = item.get_type()
            # ebooklib image type constant
            if content_type == 3:  # ITEM_IMAGE
                return item.get_content()

    return None


def read_epub_metadata(path: Path) -> BookMetadata:
    """Extract metadata from an EPUB file.

    Args:
        path: Path to the EPUB file.

    Returns:
        BookMetadata populated with extracted fields.

    Raises:
        EpubReadError: If the file cannot be read or parsed.
    """
    if not path.exists():
        raise EpubReadError(f"File not found: {path}")

    try:
        book = epub.read_epub(str(path), options={"ignore_ncx": True})
    except Exception as exc:
        raise EpubReadError(f"Failed to read EPUB: {path}: {exc}") from exc

    title = _get_metadata_value(book, "DC", "title")
    if not title:
        title = path.stem

    authors = _get_authors(book)
    identifiers = _get_identifiers(book)
    isbn = _detect_isbn(identifiers)
    cover_image = _extract_cover_image(book)

    return BookMetadata(
        title=title,
        authors=authors,
        language=_get_metadata_value(book, "DC", "language"),
        publisher=_get_metadata_value(book, "DC", "publisher"),
        isbn=isbn,
        description=_get_metadata_value(book, "DC", "description"),
        identifiers=identifiers,
        cover_image=cover_image,
        source_path=path,
    )


def _fix_toc_uids(book: epub.EpubBook) -> None:
    """Assign uids to TOC Link items that are missing them.

    ebooklib sometimes reads TOC entries without preserving the uid attribute,
    which causes lxml to fail when writing the NCX. This assigns a stable uid
    based on the link's href.
    """
    for i, item in enumerate(book.toc):
        if isinstance(item, epub.Link) and not item.uid:
            item.uid = f"navpoint-{i}"
        elif isinstance(item, tuple) and len(item) == 2:
            section, children = item
            if isinstance(section, epub.Link) and not section.uid:
                section.uid = f"navpoint-section-{i}"
            for j, child in enumerate(children):
                if isinstance(child, epub.Link) and not child.uid:
                    child.uid = f"navpoint-{i}-{j}"


def _clear_dc_metadata(book: epub.EpubBook, name: str) -> None:
    """Remove all Dublin Core metadata entries for a given field name."""
    dc_ns = "http://purl.org/dc/elements/1.1/"
    book.metadata.setdefault(dc_ns, {})
    book.metadata[dc_ns].pop(name, None)


def _set_dc_metadata(book: epub.EpubBook, name: str, value: str) -> None:
    """Set a single Dublin Core metadata value, replacing any existing entries."""
    _clear_dc_metadata(book, name)
    book.add_metadata("DC", name, value)


def write_epub_metadata(path: Path, metadata: BookMetadata) -> None:
    """Write metadata fields into an existing EPUB file.

    Reads the EPUB, updates metadata fields from the BookMetadata object,
    and writes the file back in place. Content and structure are preserved.

    Args:
        path: Path to the EPUB file to update.
        metadata: BookMetadata with the values to write.

    Raises:
        EpubReadError: If the file cannot be read or written.
    """
    if not path.exists():
        raise EpubReadError(f"File not found: {path}")

    try:
        book = epub.read_epub(str(path))
    except Exception as exc:
        raise EpubReadError(f"Failed to read EPUB: {path}: {exc}") from exc

    _set_dc_metadata(book, "title", metadata.title)

    if metadata.authors:
        _clear_dc_metadata(book, "creator")
        for author in metadata.authors:
            book.add_author(author)

    if metadata.language is not None:
        _set_dc_metadata(book, "language", metadata.language)

    if metadata.publisher is not None:
        _set_dc_metadata(book, "publisher", metadata.publisher)

    if metadata.description is not None:
        _set_dc_metadata(book, "description", metadata.description)

    _fix_toc_uids(book)

    try:
        epub.write_epub(str(path), book)
    except Exception as exc:
        raise EpubReadError(f"Failed to write EPUB: {path}: {exc}") from exc
