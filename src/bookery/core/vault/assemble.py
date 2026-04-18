# ABOUTME: Concatenates vault notes into a single pandoc-ready markdown document.
# ABOUTME: Resolves wiki-links and image embeds, optionally appending a tag index.

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from bookery.core.vault.image import build_asset_index, resolve_images
from bookery.core.vault.index import build_tag_index
from bookery.core.vault.note import Note
from bookery.core.vault.wikilink import resolve_wikilinks


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
) -> AssembledVault:
    """Concatenate notes into a single markdown doc with resolved links and assets."""
    title_to_slug = {n.title: n.slug for n in notes}
    asset_index = build_asset_index(vault_path)

    folder_to_notes: dict[str, list[Note]] = {}
    for n in notes:
        folder_to_notes.setdefault(n.relative_folder, []).append(n)

    broken_total = 0
    all_assets: list[Path] = []
    seen_assets: set[Path] = set()
    chunks: list[str] = []

    for folder in sorted(folder_to_notes):
        label = folder if folder else "(root)"
        chunks.append(f"<!-- folder: {label} -->")
        for note in folder_to_notes[folder]:
            body, broken = resolve_wikilinks(note.body, title_to_slug)
            body, assets = resolve_images(body, note_path=note.path, asset_index=asset_index)
            broken_total += broken
            for a in assets:
                resolved = a.resolve()
                if resolved not in seen_assets:
                    seen_assets.add(resolved)
                    all_assets.append(resolved)
            chunks.append(f"# {note.title} {{#{note.slug}}}")
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
