# ABOUTME: Concatenates vault notes into a single pandoc-ready markdown document.
# ABOUTME: Resolves wiki-links and image embeds, optionally appending a tag index.

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from bookery.core.vault.image import build_asset_index, resolve_images
from bookery.core.vault.index import build_tag_index
from bookery.core.vault.note import Note, display_title
from bookery.core.vault.wikilink import resolve_wikilinks

AssembleProgressFn = Callable[[int, int, str], None]

# Notes whose stripped display title starts with anything other than a letter
# bucket here. The literal hash keeps the heading short and unambiguous for
# the Kobo TOC.
_NON_LETTER_BUCKET = "#"
_NON_LETTER_BUCKET_SLUG = "hash"


def _bucket_for(title: str) -> str:
    """Return the single-character A-Z bucket label for a display title.

    Non-letter leaders (digits, symbols, empty) collapse to the ``#`` bucket
    so the alphabetical sections stay clean.
    """
    if not title:
        return _NON_LETTER_BUCKET
    first = title[0]
    if first.isalpha():
        return first.upper()
    return _NON_LETTER_BUCKET


def _bucket_sort_key(bucket: str) -> tuple[int, str]:
    """Sort the ``#`` bucket before A-Z, then alphabetically."""
    if bucket == _NON_LETTER_BUCKET:
        return (0, "")
    return (1, bucket)


def _bucket_slug(bucket: str) -> str:
    """Stable anchor slug fragment for a bucket label."""
    if bucket == _NON_LETTER_BUCKET:
        return _NON_LETTER_BUCKET_SLUG
    return bucket.lower()


def _disambiguate(notes: list[Note], display_for: dict[int, str]) -> dict[int, tuple[str, str]]:
    """Return {id(note): (display_title, unique_slug)} ensuring unique anchor slugs.

    Notes that share a *display* title (after timestamp stripping) get a folder
    hint appended to their display title (e.g. "References (Book A)") and
    incrementing suffixes on their slugs (references, references-2,
    references-3). Single-occurrence notes keep their stripped display title
    and original slug.
    """
    by_display: dict[str, list[Note]] = {}
    for n in notes:
        by_display.setdefault(display_for[id(n)], []).append(n)

    result: dict[int, tuple[str, str]] = {}
    for title, group in by_display.items():
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
    """Demote body H1/H2 down so they sit beneath the note's H3 heading.

    Folders are H1 chapters, letter buckets are H2 sections, and notes are H3
    entries. Any in-body H1 or H2 would compete with those structural headings
    in the TOC, so push body H1->H4 and body H2->H5. The H2 substitution runs
    first so demoted H1s (now starting with ``## ``) are not re-matched as
    H2s. pandoc ``--toc-depth=3`` only walks folder->bucket->note.
    """
    body = _H2_LINE_RE.sub(r"##### \1", body)
    body = _H1_LINE_RE.sub(r"#### \1", body)
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
    display_for: dict[int, str] = {id(n): display_title(n.title) for n in notes}
    disambiguated = _disambiguate(notes, display_for)
    # Wiki-link resolution: map both the original raw title and the stripped
    # display title to the (first) unique slug, so both `[[202302010942 - X]]`
    # and `[[X]]` keep landing on the right note.
    title_to_slug: dict[str, str] = {}
    for n in notes:
        slug = disambiguated[id(n)][1]
        title_to_slug.setdefault(n.title, slug)
        title_to_slug.setdefault(display_for[id(n)], slug)
    asset_index = build_asset_index(vault_path)

    folder_to_notes: dict[str, list[Note]] = {}
    for n in notes:
        folder_to_notes.setdefault(n.relative_folder, []).append(n)

    broken_total = 0
    all_assets: list[Path] = []
    seen_assets: set[Path] = set()
    chunks: list[str] = []

    total = len(notes)
    processed = 0
    for folder in sorted(folder_to_notes):
        chunks.append(f"# {_folder_label(folder)} {{#folder-{_folder_slug(folder)}}}")
        chunks.append("")
        # Group this folder's notes into letter buckets keyed by the stripped
        # display title. A note whose display title starts with a non-letter
        # leader (digit/symbol) lands in the ``#`` bucket.
        bucket_to_notes: dict[str, list[Note]] = {}
        for note in folder_to_notes[folder]:
            bucket = _bucket_for(display_for[id(note)])
            bucket_to_notes.setdefault(bucket, []).append(note)
        for bucket in sorted(bucket_to_notes, key=_bucket_sort_key):
            chunks.append(f"## {bucket} {{#bucket-{_folder_slug(folder)}-{_bucket_slug(bucket)}}}")
            chunks.append("")
            bucket_notes = sorted(
                bucket_to_notes[bucket],
                key=lambda n: display_for[id(n)].casefold(),
            )
            for note in bucket_notes:
                processed += 1
                if on_progress is not None:
                    on_progress(processed, total, note.title)
                heading, unique_slug = disambiguated[id(note)]
                body = _demote_body_headings(note.body)
                body, broken = resolve_wikilinks(body, title_to_slug)
                body, assets = resolve_images(body, note_path=note.path, asset_index=asset_index)
                broken_total += broken
                for a in assets:
                    resolved = a.resolve()
                    if resolved not in seen_assets:
                        seen_assets.add(resolved)
                        all_assets.append(resolved)
                chunks.append(f"### {heading} {{#{unique_slug}}}")
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
