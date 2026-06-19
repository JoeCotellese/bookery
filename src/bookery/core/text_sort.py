# ABOUTME: Shared article-stripping helper for title sort keys and vault filing.
# ABOUTME: English-only ("The" / "A" / "An"); multi-language is the non-goal in #175.

from __future__ import annotations

import re

# Leading English articles ignored when computing a sort key. The trailing
# `\s+(.+)$` requires at least one word after the article so bare "The" / "An"
# stays untouched. Used by `compute_title_sort` here and by vault filing in
# `core/vault/assemble.py`.
LEADING_ARTICLE_RE = re.compile(r"^(?:the|a|an)\s+(.+)$", re.IGNORECASE)


def compute_title_sort(title: str) -> str:
    """Return a sort key for ``title`` with a leading English article stripped.

    "The Hobbit" → "Hobbit", "A Wizard of Earthsea" → "Wizard of Earthsea".
    Falls back to the input when stripping would yield an empty string (e.g.
    the input is just "The"), or when no leading article is present.
    Case-insensitive at the boundary; the rest of the title's case is preserved.
    """
    if not title:
        return title
    stripped = LEADING_ARTICLE_RE.sub(r"\1", title, count=1).strip()
    return stripped or title


def compute_author_sort(authors: list[str], explicit_author_sort: str | None = None) -> str:
    """Return a sortable author key derived from an authors list.

    Mirrors `bookery.core.pathformat.derive_author_sort` but takes the raw
    list directly so the same logic powers both the write path
    (`db.mapping.metadata_to_row`) and the V10 backfill (issue #196), which
    sees a JSON authors string rather than a `BookMetadata` wrapper.

    Rules (in priority order):
    1. A truthy ``explicit_author_sort`` wins — curator/provider values stay.
    2. Empty / whitespace-only first author → "Unknown".
    3. First-author already contains a comma → assumed pre-inverted, kept as-is.
    4. Single-token first author (e.g. "Madonna") → kept as-is.
    5. Multi-token name → "Last, First Middle" (split on whitespace, last
       token first).
    """
    if explicit_author_sort:
        return explicit_author_sort
    if not authors:
        return "Unknown"
    name = authors[0].strip()
    if not name:
        return "Unknown"
    if "," in name:
        return name
    parts = name.split()
    if len(parts) == 1:
        return name
    return f"{parts[-1]}, {' '.join(parts[:-1])}"
