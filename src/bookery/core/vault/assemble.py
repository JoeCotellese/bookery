# ABOUTME: Concatenates vault notes into a single pandoc-ready markdown document.
# ABOUTME: Resolves wiki-links and image embeds, optionally appending a tag index.

from __future__ import annotations

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
        for i, n in enumerate(group, start=1):
            hint = n.relative_folder or "root"
            display = f"{title} ({hint})"
            slug = n.slug if i == 1 else f"{n.slug}-{i}"
            result[id(n)] = (display, slug)
    return result


def _strip_leading_duplicate_h1(body: str, title: str) -> str:
    """Drop the body's leading H1 when it matches the resolved title (avoids TOC duplication)."""
    stripped = body.lstrip("\n")
    if not stripped.startswith("# "):
        return body
    first_line, _, rest = stripped.partition("\n")
    heading = first_line[2:].strip()
    if heading == title.strip():
        return rest.lstrip("\n")
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

    broken_total = 0
    all_assets: list[Path] = []
    seen_assets: set[Path] = set()
    chunks: list[str] = []

    total = len(notes)
    processed = 0
    for folder in sorted(folder_to_notes):
        label = folder if folder else "(root)"
        chunks.append(f"<!-- folder: {label} -->")
        for note in folder_to_notes[folder]:
            processed += 1
            if on_progress is not None:
                on_progress(processed, total, note.title)
            display_title, unique_slug = disambiguated[id(note)]
            body = _strip_leading_duplicate_h1(note.body, note.title)
            body, broken = resolve_wikilinks(body, title_to_slug)
            body, assets = resolve_images(body, note_path=note.path, asset_index=asset_index)
            broken_total += broken
            for a in assets:
                resolved = a.resolve()
                if resolved not in seen_assets:
                    seen_assets.add(resolved)
                    all_assets.append(resolved)
            chunks.append(f"# {display_title} {{#{unique_slug}}}")
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
