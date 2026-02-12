# ABOUTME: The `bookery match` command for metadata lookup and correction.
# ABOUTME: Matches EPUBs against Open Library and writes corrected copies.

import logging
from pathlib import Path

import click
from rich.console import Console

from bookery.cli.review import ReviewSession
from bookery.core.pipeline import apply_metadata_safely
from bookery.formats.epub import EpubReadError, read_epub_metadata
from bookery.metadata.http import BookeryHttpClient
from bookery.metadata.normalizer import normalize_metadata
from bookery.metadata.openlibrary import OpenLibraryProvider
from bookery.metadata.provider import MetadataProvider

logger = logging.getLogger(__name__)

def _create_provider() -> MetadataProvider:
    """Create the default metadata provider (Open Library)."""
    http_client = BookeryHttpClient()
    return OpenLibraryProvider(http_client=http_client)


def _find_epubs(path: Path) -> list[Path]:
    """Find EPUB files at the given path (single file or directory)."""
    if path.is_file():
        return [path]
    return sorted(path.rglob("*.epub"))


@click.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "-o",
    "--output-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Directory for modified copies (default: ./bookery-output).",
)
@click.option(
    "-q",
    "--quiet",
    is_flag=True,
    default=False,
    help="Auto-accept high-confidence matches without prompting.",
)
def match(path: Path, output_dir: Path | None, quiet: bool) -> None:
    """Match EPUB metadata against Open Library and write corrected copies."""
    console = Console()

    if output_dir is None:
        output_dir = Path("bookery-output")

    provider = _create_provider()
    review = ReviewSession(
        console=console, quiet=quiet, lookup_fn=provider.lookup_by_url
    )

    epubs = _find_epubs(path)
    if not epubs:
        console.print("[yellow]No EPUB files found.[/yellow]")
        return

    total = len(epubs)
    matched = 0
    skipped = 0
    errors = 0

    for i, epub_path in enumerate(epubs, start=1):
        console.print(f"\n[bold][{i}/{total}] Processing:[/bold] {epub_path.name}")

        try:
            extracted = read_epub_metadata(epub_path)
        except EpubReadError as exc:
            console.print(f"  [red]Error reading:[/red] {exc}")
            errors += 1
            continue

        # Normalize mangled metadata for better search queries
        norm_result = normalize_metadata(extracted)
        if norm_result.was_modified:
            console.print(f"  [dim]Normalized title:[/dim] {norm_result.normalized.title}")
            if norm_result.normalized.authors != extracted.authors:
                console.print(
                    f"  [dim]Detected author:[/dim] {norm_result.normalized.author}"
                )
        search_meta = norm_result.normalized

        # Try ISBN lookup first, then fall back to title/author search
        candidates = []
        if search_meta.isbn:
            candidates = provider.search_by_isbn(search_meta.isbn)

        if not candidates:
            candidates = provider.search_by_title_author(
                search_meta.title, search_meta.author or None
            )

        if not candidates:
            console.print("  [yellow]No candidates found.[/yellow]")
            skipped += 1
            continue

        selected = review.review(extracted, candidates)
        if selected is None:
            skipped += 1
            continue

        try:
            result_path = apply_metadata_safely(epub_path, selected, output_dir)
            console.print(f"  [green]Written:[/green] {result_path}")
            matched += 1
        except (OSError, EpubReadError) as exc:
            console.print(f"  [red]Error writing:[/red] {exc}")
            errors += 1

    # Summary
    parts = []
    if matched:
        parts.append(f"[green]{matched} matched[/green]")
    if skipped:
        parts.append(f"[yellow]{skipped} skipped[/yellow]")
    if errors:
        parts.append(f"[red]{errors} error{'s' if errors != 1 else ''}[/red]")

    console.print(f"\nDone: {', '.join(parts)}")
