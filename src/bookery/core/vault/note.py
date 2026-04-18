# ABOUTME: Note dataclass plus slugify and title-resolution helpers for the vault exporter.
# ABOUTME: Title order: frontmatter `title` → first H1 in body → filename (minus timestamp + .md).

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_H1_RE = re.compile(r"^# +(.+?)\s*$", re.MULTILINE)
_TIMESTAMP_PREFIX_RE = re.compile(r"^\d{8}[-_ ]")


@dataclass(slots=True)
class Note:
    path: Path
    relative_folder: str
    title: str
    slug: str
    body: str
    frontmatter: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)


def slugify(text: str) -> str:
    """Produce a deterministic URL-safe slug suitable for EPUB anchors."""
    # Normalize unicode, drop combining marks.
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.lower()
    # Replace any run of non-alphanumeric chars with a single hyphen.
    ascii_text = re.sub(r"[^a-z0-9]+", "-", ascii_text)
    return ascii_text.strip("-")


def resolve_title(
    frontmatter_title: str | None,
    body: str,
    path: Path,
) -> str:
    """Resolve a note title using the documented fallback order."""
    if frontmatter_title and frontmatter_title.strip():
        return frontmatter_title.strip()

    match = _H1_RE.search(body)
    if match:
        return match.group(1).strip()

    stem = path.stem
    stripped = _TIMESTAMP_PREFIX_RE.sub("", stem)
    return stripped or stem
