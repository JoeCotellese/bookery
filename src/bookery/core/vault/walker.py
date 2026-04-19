# ABOUTME: Walks an Obsidian vault (optionally constrained to folders) and yields Note objects.
# ABOUTME: Parses frontmatter, resolves titles, and preserves relative folder for TOC grouping.

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from bookery.core.vault.frontmatter import parse_frontmatter
from bookery.core.vault.note import Note, resolve_title, slugify

WalkProgressFn = Callable[[int, int, Path], None]


def walk_vault(
    vault_path: Path,
    folders: list[str] | None = None,
    on_progress: WalkProgressFn | None = None,
    exclude_tags: list[str] | None = None,
) -> list[Note]:
    """Walk a vault and return Note objects for every markdown file found.

    Hidden directories (dotfiles like `.obsidian`) and hidden files are skipped.
    Non-`.md` files are ignored. When `folders` is provided, only descendants of
    those top-level folders are included. When `exclude_tags` is provided, any
    note whose frontmatter `tags` list contains one of those exact tag strings
    is dropped from the result.
    """
    excluded = set(exclude_tags or [])
    vault_path = vault_path.expanduser()
    roots = [vault_path / f for f in folders] if folders else [vault_path]

    md_files: list[Path] = []
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for p in root.rglob("*.md"):
            if _is_hidden(p, vault_path):
                continue
            md_files.append(p)

    md_files.sort()
    total = len(md_files)
    notes: list[Note] = []
    for idx, md in enumerate(md_files, start=1):
        if on_progress is not None:
            on_progress(idx, total, md)
        text = md.read_text(encoding="utf-8")
        body, fm, tags = parse_frontmatter(text)
        if excluded and any(t in excluded for t in tags):
            continue
        fm_title = fm.get("title") if isinstance(fm.get("title"), str) else None
        title = resolve_title(fm_title, body, md)
        rel_folder = _relative_folder(md, vault_path)
        notes.append(
            Note(
                path=md,
                relative_folder=rel_folder,
                title=title,
                slug=slugify(title),
                body=body,
                frontmatter=fm,
                tags=tags,
            )
        )
    return notes


def _is_hidden(path: Path, vault_root: Path) -> bool:
    try:
        rel = path.relative_to(vault_root)
    except ValueError:
        rel = path
    return any(part.startswith(".") for part in rel.parts)


def _relative_folder(md: Path, vault_root: Path) -> str:
    try:
        rel = md.relative_to(vault_root)
    except ValueError:
        return ""
    parent = rel.parent
    if str(parent) == ".":
        return ""
    return str(parent)
