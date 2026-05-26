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
