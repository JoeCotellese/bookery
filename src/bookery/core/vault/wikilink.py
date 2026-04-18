# ABOUTME: Resolves Obsidian `[[wiki-link]]` and `[[wiki-link|alias]]` syntax.
# ABOUTME: Rewrites to intra-document anchor links; broken links become italic plain text.

from __future__ import annotations

import re

_WIKILINK_RE = re.compile(r"\[\[([^\[\]|]+?)(?:\|([^\[\]]+?))?\]\]")


def resolve_wikilinks(body: str, title_to_slug: dict[str, str]) -> tuple[str, int]:
    """Rewrite `[[...]]` occurrences using a case-insensitive title → slug map.

    Returns `(rewritten_body, broken_count)`. Broken links render as `*text*`.
    """
    lowered = {k.lower(): v for k, v in title_to_slug.items()}
    broken = 0

    def _sub(match: re.Match[str]) -> str:
        nonlocal broken
        target = match.group(1).strip()
        alias = match.group(2)
        display = (alias.strip() if alias else target)
        slug = lowered.get(target.lower())
        if slug is None:
            broken += 1
            return f"*{display}*"
        return f"[{display}](#{slug})"

    rewritten = _WIKILINK_RE.sub(_sub, body)
    return rewritten, broken
