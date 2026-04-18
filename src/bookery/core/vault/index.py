# ABOUTME: Builds a tag index section for the vault export EPUB.
# ABOUTME: Tags are alphabetised, prefixes can be excluded, and rare tags can be hidden.

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from bookery.core.vault.note import Note


@dataclass(slots=True)
class TagIndex:
    markdown: str
    notes_without_tags: list[str]


def build_tag_index(
    notes: list[Note],
    exclude_prefixes: list[str] | None = None,
    min_count: int = 1,
) -> TagIndex:
    """Build a markdown tag index from a list of notes."""
    exclude_prefixes = exclude_prefixes or []
    tag_to_notes: dict[str, list[Note]] = defaultdict(list)
    notes_without_tags: list[str] = []

    for note in notes:
        if not note.tags:
            notes_without_tags.append(note.title)
            continue
        for tag in note.tags:
            if any(tag.startswith(p) for p in exclude_prefixes):
                continue
            tag_to_notes[tag].append(note)

    lines: list[str] = ["# Tag Index", ""]
    for tag in sorted(tag_to_notes):
        bucket = tag_to_notes[tag]
        if len(bucket) < min_count:
            continue
        lines.append(f"## {tag}")
        lines.append("")
        for note in sorted(bucket, key=lambda n: n.title.lower()):
            lines.append(f"- [{note.title}](#{note.slug})")
        lines.append("")

    markdown = "\n".join(lines).rstrip() + "\n"
    return TagIndex(markdown=markdown, notes_without_tags=notes_without_tags)
