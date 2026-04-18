# ABOUTME: YAML frontmatter parser for Obsidian notes.
# ABOUTME: Strips the `---` block, returns remaining body, parsed dict, and normalised tag list.

from __future__ import annotations

from typing import Any

import yaml


def parse_frontmatter(text: str) -> tuple[str, dict[str, Any], list[str]]:
    """Split a note into (body, frontmatter_dict, tags).

    Malformed frontmatter is treated as content (body returned unchanged, empty dict).
    """
    if not text.startswith("---"):
        return text, {}, []

    # Split on the first two `---` fences.
    lines = text.split("\n")
    if len(lines) < 2 or lines[0].strip() != "---":
        return text, {}, []

    end_idx: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return text, {}, []

    fm_text = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1 :])

    try:
        loaded = yaml.safe_load(fm_text) if fm_text.strip() else {}
    except yaml.YAMLError:
        return text, {}, []

    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        return text, {}, []

    tags = _normalize_tags(loaded.get("tags"))
    return body, loaded, tags


def _normalize_tags(raw: Any) -> list[str]:
    """Obsidian accepts tags as a list or a whitespace-separated string; flatten either."""
    if raw is None:
        return []
    if isinstance(raw, str):
        items = raw.split()
    elif isinstance(raw, list):
        items = [str(x) for x in raw]
    else:
        return []
    cleaned = [item.lstrip("#").strip() for item in items]
    return [t for t in cleaned if t]
