# ABOUTME: Cover image extraction with on-disk cache for the web cover route.
# ABOUTME: Lazy-extracts from EPUB on first request, caches to <library_root>/.covers/.

import contextlib
from pathlib import Path

from bookery.formats.epub import extract_cover_bytes

# Inline SVG placeholder served when a book has no extractable cover.
# Kept tiny so the response is cheap to send repeatedly and the same bytes
# can be cached aggressively by clients. Renders as a book-icon glyph in
# muted greys that fit either the list thumb (40x60) or the detail hero
# (160x240) via the surrounding <img> sizing.
PLACEHOLDER_SVG: bytes = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 60" '
    b'preserveAspectRatio="xMidYMid meet" role="img" aria-label="No cover">'
    b'<rect width="40" height="60" fill="#e5e5e5"/>'
    b'<rect x="6" y="8" width="28" height="44" fill="#bdbdbd" stroke="#9e9e9e" stroke-width="1"/>'
    b'<line x1="11" y1="20" x2="29" y2="20" stroke="#7d7d7d" stroke-width="1.2"/>'
    b'<line x1="11" y1="28" x2="29" y2="28" stroke="#7d7d7d" stroke-width="1.2"/>'
    b'<line x1="11" y1="36" x2="25" y2="36" stroke="#7d7d7d" stroke-width="1.2"/>'
    b"</svg>"
)
PLACEHOLDER_CONTENT_TYPE: str = "image/svg+xml"


_EXTENSION_FOR_CONTENT_TYPE: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}


def _cache_dir(library_root: Path) -> Path:
    """Return the cover cache directory for ``library_root`` (created on demand)."""
    cache = library_root / ".covers"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _cached_path(library_root: Path, book_id: int, content_type: str) -> Path:
    """Compute the on-disk cache path for a book's cover at ``content_type``."""
    ext = _EXTENSION_FOR_CONTENT_TYPE.get(content_type, ".bin")
    return _cache_dir(library_root) / f"{book_id}{ext}"


def _find_cached(library_root: Path, book_id: int) -> tuple[bytes, str] | None:
    """Return cached bytes + content-type for ``book_id``, if cached.

    Probes every known extension so we don't have to remember which media
    type the original extraction produced. This keeps the route stateless
    across process restarts.
    """
    cache = library_root / ".covers"
    if not cache.exists():
        return None
    for content_type, ext in _EXTENSION_FOR_CONTENT_TYPE.items():
        path = cache / f"{book_id}{ext}"
        if path.exists():
            return path.read_bytes(), content_type
    return None


def get_or_extract_cover(
    book_id: int,
    epub_path: Path | None,
    library_root: Path,
) -> tuple[bytes, str]:
    """Return ``(bytes, content_type)`` for a book's cover.

    Resolution order: in-memory placeholder for missing source; on-disk cache
    if present; otherwise extract from the EPUB and write the cache. When
    extraction fails (no cover, unreadable file), the placeholder SVG is
    returned but **not** cached to disk — re-importing a file with a cover
    later should not be defeated by a sticky placeholder. The route caller is
    free to set ``Cache-Control`` so the client still serves the placeholder
    from its own cache between requests.
    """
    if epub_path is None or not epub_path.exists():
        return PLACEHOLDER_SVG, PLACEHOLDER_CONTENT_TYPE

    cached = _find_cached(library_root, book_id)
    if cached is not None:
        return cached

    result = extract_cover_bytes(epub_path)
    if result is None:
        return PLACEHOLDER_SVG, PLACEHOLDER_CONTENT_TYPE

    data, content_type = result
    # Cache writes are best-effort. Serving the bytes is what matters;
    # a read-only or full disk should not break the route.
    with contextlib.suppress(OSError):
        _cached_path(library_root, book_id, content_type).write_bytes(data)
    return data, content_type
