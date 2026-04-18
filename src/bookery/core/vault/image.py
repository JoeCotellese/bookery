# ABOUTME: Resolves Obsidian image embeds `![[asset]]` and standard `![alt](path)` markdown.
# ABOUTME: Rewrites both to filename-relative pandoc syntax and collects absolute asset paths.

from __future__ import annotations

import re
from pathlib import Path

_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".tiff"}
_OBSIDIAN_EMBED_RE = re.compile(r"!\[\[([^\[\]|]+?)(?:\|([^\[\]]+?))?\]\]")
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def build_asset_index(vault_path: Path) -> dict[str, Path]:
    """Index every asset file in the vault by bare filename (Obsidian-flat lookup)."""
    index: dict[str, Path] = {}
    for p in vault_path.rglob("*"):
        if not p.is_file():
            continue
        if any(part.startswith(".") for part in p.relative_to(vault_path).parts):
            continue
        if p.suffix.lower() in _IMAGE_EXT:
            index.setdefault(p.name, p)
    return index


def resolve_images(
    body: str,
    note_path: Path,
    asset_index: dict[str, Path],
) -> tuple[str, list[Path]]:
    """Rewrite image references; return updated body and the list of embedded assets."""
    assets: list[Path] = []

    def _sub_obsidian(match: re.Match[str]) -> str:
        target = match.group(1).strip()
        alias = match.group(2)
        asset = asset_index.get(target)
        if asset is None:
            return f"*{target}*"
        assets.append(asset)
        display = alias.strip() if alias else target
        return f"![{display}]({asset.name})"

    def _sub_md(match: re.Match[str]) -> str:
        alt = match.group(1)
        src = match.group(2).strip()
        if src.startswith(("http://", "https://", "/")):
            return match.group(0)
        # Resolve relative to the note's directory; fall back to flat asset lookup.
        candidate = (note_path.parent / src).resolve()
        if not candidate.exists():
            fallback = asset_index.get(Path(src).name)
            if fallback is None:
                return match.group(0)
            candidate = fallback
        assets.append(candidate)
        return f"![{alt}]({candidate.name})"

    # Process standard markdown images first so the output of the Obsidian
    # pass (which produces `![alt](filename)`) is not re-matched.
    body = _MD_IMAGE_RE.sub(_sub_md, body)
    body = _OBSIDIAN_EMBED_RE.sub(_sub_obsidian, body)
    return body, assets
