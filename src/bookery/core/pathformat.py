# ABOUTME: Path formatting for organized output directory structure.
# ABOUTME: Sanitizes filenames, derives author sort keys, and builds author/title paths.

import re
import unicodedata
from pathlib import Path

from bookery.metadata.types import BookMetadata

# Characters unsafe for common filesystems (Windows, macOS, Linux)
_UNSAFE_CHARS = re.compile(r'[/\\:*?"<>|]')

# Runs of dashes or whitespace to collapse
_DASH_RUNS = re.compile(r"-{2,}")
_SPACE_RUNS = re.compile(r" {2,}")

# Leading/trailing dots, spaces, and dashes
_EDGE_JUNK = re.compile(r"^[\s.\-]+|[\s.\-]+$")

_MAX_BYTES = 255
_MAX_COLLISION_ATTEMPTS = 10_000


def sanitize_component(name: str, *, fallback: str = "Unknown") -> str:
    """Sanitize a string for use as a filesystem path component.

    Replaces unsafe characters, collapses runs, strips edges, truncates to
    255 UTF-8 bytes, and applies NFC normalization. Returns the fallback
    string if the result is empty.
    """
    # NFC normalize first
    result = unicodedata.normalize("NFC", name)

    # Replace unsafe chars with dash
    result = _UNSAFE_CHARS.sub("-", result)

    # Collapse runs of dashes and spaces
    result = _DASH_RUNS.sub("-", result)
    result = _SPACE_RUNS.sub(" ", result)

    # Strip leading/trailing junk
    result = _EDGE_JUNK.sub("", result)

    # Truncate to 255 bytes without splitting codepoints
    encoded = result.encode("utf-8")
    if len(encoded) > _MAX_BYTES:
        encoded = encoded[:_MAX_BYTES]
        # Decode with error handling to avoid partial codepoints
        result = encoded.decode("utf-8", errors="ignore")
        # Re-strip trailing junk that truncation may have exposed
        result = _EDGE_JUNK.sub("", result)

    if not result:
        return fallback

    return result


def derive_author_sort(metadata: BookMetadata) -> str:
    """Derive a sortable author string from BookMetadata.

    Priority: author_sort field > first author inverted > "Unknown".
    Single-word names and names already containing commas are kept as-is.
    Multi-word names are inverted: "First Middle Last" -> "Last, First Middle".
    """
    if metadata.author_sort:
        return metadata.author_sort

    if not metadata.authors:
        return "Unknown"

    name = metadata.authors[0].strip()
    if not name:
        return "Unknown"

    # Already contains a comma — assume it's already "Last, First"
    if "," in name:
        return name

    parts = name.split()
    if len(parts) == 1:
        return name

    # Invert: "First Middle Last" -> "Last, First Middle"
    return f"{parts[-1]}, {' '.join(parts[:-1])}"


def build_output_path(
    metadata: BookMetadata,
    output_dir: Path,
    *,
    extension: str = ".epub",
) -> Path:
    """Build an organized output path: output_dir / author_sort / title.ext.

    Components are sanitized for filesystem safety.
    """
    author_dir = sanitize_component(derive_author_sort(metadata))
    title = sanitize_component(metadata.title, fallback="Untitled")

    return output_dir / author_dir / f"{title}{extension}"


def resolve_collision(output_path: Path) -> Path:
    """Find a non-colliding filename by appending _1, _2, etc.

    Returns the original path if no collision exists.
    """
    if not output_path.exists():
        return output_path

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


_MANIFEST_NAME = ".bookery-processed"


def record_processed(output_dir: Path, source_name: str) -> None:
    """Record a source filename as processed in the output directory manifest."""
    manifest = output_dir / _MANIFEST_NAME
    output_dir.mkdir(parents=True, exist_ok=True)
    with manifest.open("a", encoding="utf-8") as f:
        f.write(source_name + "\n")


def is_processed(output_dir: Path, source_name: str) -> bool:
    """Check if a source filename has been recorded as processed."""
    manifest = output_dir / _MANIFEST_NAME
    if not manifest.exists():
        return False
    return source_name in manifest.read_text(encoding="utf-8").splitlines()
