# ABOUTME: Invokes pandoc to convert an assembled vault markdown into an EPUB.
# ABOUTME: Also exposes stable_uuid for deterministic re-sync to Kobo via dc:identifier.

from __future__ import annotations

import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path


class PandocMissingError(RuntimeError):
    """Raised when pandoc is not found on PATH."""


class PandocRenderError(RuntimeError):
    """Raised when pandoc exits non-zero."""


@dataclass(slots=True)
class EpubMetadata:
    title: str
    author: str
    identifier: str
    version_label: str | None = None


def stable_uuid(vault_path: Path) -> str:
    """Deterministic UUID5 derived from the absolute vault path; returned as urn:uuid:..."""
    abs_path = str(vault_path.expanduser().resolve())
    uid = uuid.uuid5(uuid.NAMESPACE_URL, f"obsidian-vault:{abs_path}")
    return f"urn:uuid:{uid}"


def random_uuid() -> str:
    return f"urn:uuid:{uuid.uuid4()}"


def render_epub(
    markdown: str,
    assets: list[Path],
    metadata: EpubMetadata,
    output_path: Path,
) -> None:
    """Render markdown to an EPUB via pandoc. Raises PandocMissingError if not installed."""
    pandoc = shutil.which("pandoc")
    if pandoc is None:
        raise PandocMissingError("pandoc not found on PATH; install pandoc to use vault-export")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        md_file = tmp_path / "vault.md"
        md_file.write_text(markdown, encoding="utf-8")

        # Copy assets next to the markdown so pandoc can resolve them by filename.
        for asset in assets:
            try:
                shutil.copy2(asset, tmp_path / asset.name)
            except FileNotFoundError:
                continue

        title = metadata.title
        if metadata.version_label:
            title = f"{title} — {metadata.version_label}"

        # Disable yaml_metadata_block so stray `---` lines in note bodies
        # (frontmatter remnants, horizontal rules) do not get interpreted as
        # document metadata. Disable multiline_tables because it greedily
        # consumes subsequent `# Heading` lines into a single sprawling table
        # once any note body contains a `---` thematic break, which dropped
        # hundreds of chapters and broke every cross-note link in real-world
        # vault exports.
        cmd = [
            pandoc,
            "-f",
            "markdown-yaml_metadata_block-multiline_tables",
            "-t",
            "epub",
            "--toc",
            # One TOC entry per note; in-body H2/H3 subheadings stay in the
            # note text but do not clutter the top-level table of contents.
            "--toc-depth=1",
            "--metadata",
            f"title={title}",
            "--metadata",
            f"author={metadata.author}",
            "--metadata",
            f"identifier={metadata.identifier}",
            "-o",
            str(output_path),
            str(md_file),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp_path)
        if result.returncode != 0:
            raise PandocRenderError(
                f"pandoc failed ({result.returncode}): {result.stderr.strip()}"
            )
