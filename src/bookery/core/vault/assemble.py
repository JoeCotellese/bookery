# ABOUTME: Concatenates vault notes into a single pandoc-ready markdown document.
# ABOUTME: Resolves wiki-links and image embeds, optionally appending a tag index.

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from bookery.core.vault.image import build_asset_index, resolve_images
from bookery.core.vault.index import build_tag_index
from bookery.core.vault.note import Note
from bookery.core.vault.wikilink import resolve_wikilinks

AssembleProgressFn = Callable[[int, int, str], None]


def _disambiguate(notes: list[Note]) -> dict[int, tuple[str, str]]:
    """Return {id(note): (display_title, unique_slug)} ensuring unique anchor slugs.

    Notes that share a title get a folder hint appended to their display title
    (e.g. "References (Book A)") and incrementing suffixes on their slugs
    (references, references-2, references-3). Single-occurrence notes keep
    their original title and slug.
    """
    by_title: dict[str, list[Note]] = {}
    for n in notes:
        by_title.setdefault(n.title, []).append(n)

    result: dict[int, tuple[str, str]] = {}
    for title, group in by_title.items():
        if len(group) == 1:
            n = group[0]
            result[id(n)] = (title, n.slug)
            continue
        # Prefer the folder name as the hint. If two notes in the group share
        # a folder, fall back to the filename stem so every display is unique.
        folder_hints = [n.relative_folder or "root" for n in group]
        use_stem = len(set(folder_hints)) < len(group)
        for i, n in enumerate(group, start=1):
            hint = n.path.stem if use_stem else (n.relative_folder or "root")
            display = f"{title} ({hint})"
            slug = n.slug if i == 1 else f"{n.slug}-{i}"
            result[id(n)] = (display, slug)
    return result


_H1_LINE_RE = re.compile(r"^# (.+)$", re.MULTILINE)
_H2_LINE_RE = re.compile(r"^## (.+)$", re.MULTILINE)
_FOLDER_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _folder_slug(folder: str) -> str:
    """Stable slug for a folder anchor: lowercased, non-alphanum collapsed to '-'.

    Empty (root) folder maps to "root" so its anchor is deterministic.
    """
    if not folder:
        return "root"
    slug = _FOLDER_SLUG_RE.sub("-", folder.lower()).strip("-")
    return slug or "root"


def _folder_label(folder: str) -> str:
    """Display label for a folder chapter heading. Root folder gets 'Notes'."""
    return folder if folder else "Notes"


def _demote_body_headings(body: str) -> str:
    """Demote body H1/H2 down two levels so they sit beneath the note's H2.

    Folders are H1 chapters and notes are H2 sections, so any in-body H1 or H2
    would compete with chapter/section headings in the TOC. Pushing body H1→H3
    and body H2→H4 keeps the TOC clean (pandoc ``--toc-depth=2`` only walks
    folder→note) while preserving the body's heading text and relative
    hierarchy. The H2 substitution runs first so demoted H1s (now starting
    with ``## ``) are not re-matched as H2s.
    """
    body = _H2_LINE_RE.sub(r"#### \1", body)
    body = _H1_LINE_RE.sub(r"### \1", body)
    return body


@dataclass(slots=True)
class AssembledVault:
    markdown: str
    asset_paths: list[Path] = field(default_factory=list)
    broken_link_count: int = 0
    notes_without_tags: list[str] = field(default_factory=list)


def assemble_vault(
    notes: list[Note],
    vault_path: Path,
    include_index: bool = False,
    index_exclude_prefixes: list[str] | None = None,
    index_min_count: int = 1,
    on_progress: AssembleProgressFn | None = None,
) -> AssembledVault:
    """Concatenate notes into a single markdown doc with resolved links and assets."""
    disambiguated = _disambiguate(notes)
    # Wiki-link resolution: map the *original* title to the (first) unique slug,
    # so `[[References]]` keeps landing on the first References note.
    title_to_slug: dict[str, str] = {}
    for n in notes:
        title_to_slug.setdefault(n.title, disambiguated[id(n)][1])
    asset_index = build_asset_index(vault_path)

    folder_to_notes: dict[str, list[Note]] = {}
    for n in notes:
        folder_to_notes.setdefault(n.relative_folder, []).append(n)
    # Sort notes within each folder alphabetically (case-insensitive) so the
    # Kobo TOC reads predictably A→Z under each folder chapter.
    for folder_notes in folder_to_notes.values():
        folder_notes.sort(key=lambda n: n.title.casefold())

    broken_total = 0
    all_assets: list[Path] = []
    seen_assets: set[Path] = set()
    chunks: list[str] = []

    total = len(notes)
    processed = 0
    for folder in sorted(folder_to_notes):
        chunks.append(f"# {_folder_label(folder)} {{#folder-{_folder_slug(folder)}}}")
        chunks.append("")
        for note in folder_to_notes[folder]:
            processed += 1
            if on_progress is not None:
                on_progress(processed, total, note.title)
            display_title, unique_slug = disambiguated[id(note)]
            body = _demote_body_headings(note.body)
            body, broken = resolve_wikilinks(body, title_to_slug)
            body, assets = resolve_images(body, note_path=note.path, asset_index=asset_index)
            broken_total += broken
            for a in assets:
                resolved = a.resolve()
                if resolved not in seen_assets:
                    seen_assets.add(resolved)
                    all_assets.append(resolved)
            chunks.append(f"## {display_title} {{#{unique_slug}}}")
            chunks.append("")
            chunks.append(body.rstrip())
            chunks.append("")

    notes_without_tags: list[str] = []
    if include_index:
        tag_index = build_tag_index(
            notes,
            exclude_prefixes=index_exclude_prefixes,
            min_count=index_min_count,
        )
        chunks.append(tag_index.markdown)
        notes_without_tags = tag_index.notes_without_tags

    markdown = "\n".join(chunks).rstrip() + "\n"
    return AssembledVault(
        markdown=markdown,
        asset_paths=all_assets,
        broken_link_count=broken_total,
        notes_without_tags=notes_without_tags,
    )
