# ABOUTME: EPUB metadata extraction and writing using ebooklib.
# ABOUTME: Defensive wrapper that handles malformed files gracefully.

import contextlib
import logging
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import ebooklib
from ebooklib import epub

from bookery.core.text_sort import compute_author_sort
from bookery.metadata.types import BookMetadata
from bookery.util.text import strip_html

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


def _strip_description(value: str | None) -> str | None:
    """Strip HTML markup from a DC:description value read from the OPF.

    Publishers and conversion tools commonly wrap descriptions in ``<p>`` or
    ``<div>`` tags, and the raw OPF string carries entity escapes (``&amp;``,
    ``&#x27;``). Normalize to plain text so the catalog stores the same shape
    regardless of where the metadata came from.
    """
    if value is None:
        return None
    stripped = strip_html(value)
    return stripped or None


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
    item = _find_cover_item(book)
    return item.get_content() if item is not None else None


def _find_cover_item(book: epub.EpubBook):
    """Locate the cover image manifest item, or None.

    Follows the EPUB cover convention: an OPF meta tag ``<meta name="cover"
    content="cover-id"/>`` points at the manifest entry. Falls back to any
    item with ``cover`` in its id or filename whose type registers as an
    image or cover. Used by both metadata extraction and the web cover
    route so the same resolution rules apply everywhere.
    """
    # Check for cover image in metadata
    cover_id = None
    meta_entries = book.get_metadata("OPF", "cover")
    if meta_entries:
        cover_id = meta_entries[0][1].get("content")

    if cover_id:
        cover_item = book.get_item_with_id(cover_id)
        if cover_item is not None:
            return cover_item

    # Fallback: look for items with "cover" in the id or filename
    for item in book.get_items():
        item_id = item.get_id() or ""
        item_name = item.get_name() or ""
        if "cover" in item_id.lower() or "cover" in item_name.lower():
            content_type = item.get_type()
            if content_type in (ebooklib.ITEM_IMAGE, ebooklib.ITEM_COVER):
                return item
    return None


_IMAGE_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),  # WEBP starts with RIFF....WEBP
)


def _guess_image_content_type(data: bytes, fallback: str | None = None) -> str:
    """Best-effort image content-type from magic bytes.

    The OPF media-type attribute is the authoritative answer, but it's not
    always set or reliable. Sniffing the file header recovers JPEG/PNG/GIF/WEBP
    without pulling in Pillow. Falls back to the supplied ``fallback`` (typically
    the manifest's media_type), then ``image/jpeg`` as a last resort — every
    modern browser will still render the bytes correctly with that guess.
    """
    for magic, content_type in _IMAGE_MAGIC:
        if data.startswith(magic):
            return content_type
    if fallback:
        return fallback
    return "image/jpeg"


def extract_cover_bytes(path: Path) -> tuple[bytes, str] | None:
    """Read an EPUB and return ``(cover_bytes, content_type)`` if present.

    Returns ``None`` when the file is missing, unreadable, or has no cover
    image. The content type is sniffed from the image header so callers can
    set an accurate ``Content-Type`` without parsing OPF media-type
    attributes themselves. Used by the web ``/books/<id>/cover`` route via
    the on-disk cover cache.
    """
    if not path.exists():
        return None
    try:
        book = epub.read_epub(str(path), options={"ignore_ncx": True})
    except Exception:
        return None
    item = _find_cover_item(book)
    if item is None:
        return None
    data = item.get_content()
    if not data:
        return None
    fallback = getattr(item, "media_type", None) or None
    return data, _guess_image_content_type(data, fallback=fallback)


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
        description=_strip_description(_get_metadata_value(book, "DC", "description")),
        identifiers=identifiers,
        cover_image=cover_image,
        source_path=path,
    )


def _fix_toc_uids(book: epub.EpubBook) -> None:
    """Assign uids to TOC Link items that are missing them.

    ebooklib sometimes reads TOC entries without preserving the uid attribute,
    which causes lxml to fail when writing the NCX. This walks the TOC tree
    at arbitrary depth and assigns stable uids to any Link missing one.
    """
    _fix_toc_items(book.toc, prefix="navpoint")


def _fix_toc_items(items: list, prefix: str) -> None:
    """Recursively fix uids on TOC items at any nesting depth."""
    for i, item in enumerate(items):
        if isinstance(item, epub.Link) and not item.uid:
            item.uid = f"{prefix}-{i}"
        elif isinstance(item, tuple) and len(item) == 2:
            section, children = item
            if isinstance(section, epub.Link) and not section.uid:
                section.uid = f"{prefix}-section-{i}"
            _fix_toc_items(children, prefix=f"{prefix}-{i}")


def _scrub_none_metadata(book: epub.EpubBook) -> None:
    """Remove metadata entries with None values that would crash lxml.

    ebooklib preserves OPF meta tags like <meta name="cover" content="..."/>
    as (None, {attrs}) tuples. lxml rejects None when serializing to XML.

    If scrubbing removes the book's uid identifier, a new UUID is generated
    to prevent ebooklib from crashing when writing the NCX.
    """
    for ns in book.metadata:
        for name in list(book.metadata[ns]):
            entries = book.metadata[ns][name]
            cleaned = [(v, a) for v, a in entries if v is not None]
            if len(cleaned) < len(entries):
                logger.debug(
                    "Scrubbed %d None metadata entries from %s/%s",
                    len(entries) - len(cleaned),
                    ns,
                    name,
                )
                book.metadata[ns][name] = cleaned

    # If scrubbing removed the uid identifier, generate a replacement
    if book.uid is None:
        import uuid

        new_uid = str(uuid.uuid4())
        book.set_unique_metadata("DC", "identifier", new_uid, {"id": "bookery-uid"})
        book.uid = new_uid
        logger.debug("Generated replacement uid: %s", new_uid)


def _scrub_none_guide(book: epub.EpubBook) -> None:
    """Remove guide entries with None href/type that would crash lxml.

    Some EPUBs contain empty guide references with all-None fields.
    """
    original_len = len(book.guide)
    book.guide = [
        entry
        for entry in book.guide
        if entry.get("href") is not None and entry.get("type") is not None
    ]
    removed = original_len - len(book.guide)
    if removed:
        logger.debug("Scrubbed %d empty guide entries", removed)


def _clear_dc_metadata(book: epub.EpubBook, name: str) -> None:
    """Remove all Dublin Core metadata entries for a given field name."""
    dc_ns = "http://purl.org/dc/elements/1.1/"
    book.metadata.setdefault(dc_ns, {})
    book.metadata[dc_ns].pop(name, None)


def _set_dc_metadata(book: epub.EpubBook, name: str, value: str) -> None:
    """Set a single Dublin Core metadata value, replacing any existing entries."""
    _clear_dc_metadata(book, name)
    book.add_metadata("DC", name, value)


def creator_file_as_pairs(metadata: BookMetadata) -> list[tuple[str, str]]:
    """Return ``(author, file_as)`` pairs as written to the OPF.

    ``file_as`` is the surname-first sort key a reader uses to file the author:
    the curator-set ``author_sort`` for the primary author when present,
    otherwise derived per author via ``compute_author_sort``. Shared by the
    write path and the ``authors fix-sort`` backfill so they can't drift.
    """
    pairs: list[tuple[str, str]] = []
    for index, author in enumerate(metadata.authors):
        if index == 0 and metadata.author_sort:
            file_as = metadata.author_sort
        else:
            file_as = compute_author_sort([author])
        pairs.append((author, file_as))
    return pairs


def _clear_creator_file_as(book: epub.EpubBook) -> None:
    """Drop existing ``file-as`` refines meta so re-writes don't accumulate them.

    ebooklib stores an author's sort key as a separate ``<meta refines="#uid"
    property="file-as">`` entry under the OPF (``None``) namespace, which
    ``_clear_dc_metadata(book, "creator")`` does not touch. Without clearing it,
    re-running the write piles stale file-as entries onto each creator.
    """
    for ns_entries in book.metadata.values():
        meta = ns_entries.get("meta")
        if not meta:
            continue
        kept = [
            (value, attrs)
            for value, attrs in meta
            if not (isinstance(attrs, dict) and attrs.get("property") == "file-as")
        ]
        if len(kept) != len(meta):
            ns_entries["meta"] = kept


_OPF_NS = "http://www.idpf.org/2007/opf"
_DC_NS = "http://purl.org/dc/elements/1.1/"
_CONTAINER = "META-INF/container.xml"


def read_creator_file_as(path: Path) -> list[tuple[str, str | None]]:
    """Return ``(creator, file_as)`` pairs from an EPUB's OPF, in document order.

    Handles both EPUB2 (``opf:file-as`` attribute on ``dc:creator``) and EPUB3
    (a ``<meta refines="#id" property="file-as">`` pointing at the creator's
    ``id``). ``file_as`` is ``None`` when the creator declares no sort key.
    """
    with zipfile.ZipFile(path) as zf:
        container = ET.fromstring(zf.read(_CONTAINER))
        rootfile = container.find(".//{*}rootfile")
        opf_path = rootfile.get("full-path") if rootfile is not None else None
        if not opf_path:
            return []
        opf = ET.fromstring(zf.read(opf_path))

    # EPUB3 file-as refines, keyed by the creator id they refine.
    refines: dict[str, str] = {}
    for meta in opf.iter(f"{{{_OPF_NS}}}meta"):
        target = meta.get("refines")
        if meta.get("property") == "file-as" and target:
            refines[target.lstrip("#")] = (meta.text or "").strip()

    pairs: list[tuple[str, str | None]] = []
    for creator in opf.iter(f"{{{_DC_NS}}}creator"):
        name = (creator.text or "").strip()
        if not name:
            continue
        file_as = creator.get(f"{{{_OPF_NS}}}file-as")
        if file_as is None:
            file_as = refines.get(creator.get("id", ""))
        pairs.append((name, file_as))
    return pairs


_COVER_EXTENSION_FOR_CONTENT_TYPE: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
}


def _remove_existing_cover(book: epub.EpubBook) -> None:
    """Drop any existing cover image item and the ``<meta name="cover">`` tags.

    ``EpubBook.set_cover`` is single-use: calling it on a book that already has
    a cover would leave a duplicate image item and a second cover meta entry.
    Clearing the prior cover first keeps the write idempotent so re-enrichment
    swaps the cover cleanly rather than stacking items.
    """
    cover_item = _find_cover_item(book)
    if cover_item is not None:
        with contextlib.suppress(ValueError, KeyError):
            book.items.remove(cover_item)

    # OPF cover meta tags live under the OPF namespace as ("meta", ...) or as a
    # "cover" name depending on how ebooklib parsed them. Strip both shapes.
    for ns in list(book.metadata):
        ns_entries = book.metadata.get(ns, {})
        for name in list(ns_entries):
            entries = ns_entries[name]
            kept = [
                (value, attrs)
                for value, attrs in entries
                if not (isinstance(attrs, dict) and attrs.get("name") == "cover")
            ]
            if name == "cover":
                kept = []
            if len(kept) != len(entries):
                ns_entries[name] = kept


def _write_cover_image(book: epub.EpubBook, cover_image: bytes) -> None:
    """Embed ``cover_image`` as the EPUB cover, replacing any existing cover.

    The image bytes are sniffed for a content type so the cover item carries a
    sensible filename extension; ebooklib's ``set_cover`` then registers the
    image, a cover page, and the ``<meta name="cover">`` pointer.
    """
    _remove_existing_cover(book)
    content_type = _guess_image_content_type(cover_image)
    ext = _COVER_EXTENSION_FOR_CONTENT_TYPE.get(content_type, "jpg")
    # create_page=False skips the generated cover XHTML page. That page relies
    # on ebooklib's "cover" template, which is absent when the book was read
    # from an existing EPUB rather than freshly constructed — generating it then
    # serializes an empty document and ebooklib raises. The image item plus the
    # ``<meta name="cover">`` pointer are all readers (and _find_cover_item) need.
    book.set_cover(f"cover.{ext}", cover_image, create_page=False)


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
        _clear_creator_file_as(book)
        for index, (author, file_as) in enumerate(creator_file_as_pairs(metadata)):
            # Each creator needs a distinct id so its file-as refines meta binds
            # to the right author; ebooklib defaults every author to uid
            # "creator", which would collapse co-authors onto one sort key.
            uid = "creator" if index == 0 else f"creator{index}"
            book.add_author(author, file_as=file_as, uid=uid)

    if metadata.language is not None:
        _set_dc_metadata(book, "language", metadata.language)

    if metadata.publisher is not None:
        _set_dc_metadata(book, "publisher", metadata.publisher)

    if metadata.description is not None:
        _set_dc_metadata(book, "description", metadata.description)

    if metadata.cover_image:
        _write_cover_image(book, metadata.cover_image)

    _fix_toc_uids(book)
    _scrub_none_metadata(book)
    _scrub_none_guide(book)

    try:
        epub.write_epub(str(path), book)
    except Exception as exc:
        raise EpubReadError(f"Failed to write EPUB: {path}: {exc}") from exc
