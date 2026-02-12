# ABOUTME: The `bookery match` command for metadata lookup and correction.
# ABOUTME: Matches EPUBs against Open Library and writes corrected copies.

import logging
import re
from pathlib import Path

import click
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
)

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


def _is_already_processed(epub_path: Path, output_dir: Path) -> bool:
    """Check if an EPUB has already been written to the output directory.

    Matches by direct filename or collision-suffixed variants (_1, _2, etc.).
    """
    if (output_dir / epub_path.name).exists():
        return True
    # Check for collision suffixes: {stem}_1.epub, {stem}_2.epub, ...
    pattern = re.compile(re.escape(epub_path.stem) + r"_\d+" + re.escape(epub_path.suffix))
    return any(pattern.fullmatch(child.name) for child in output_dir.iterdir())


def _make_progress(console: Console) -> Progress:
    """Create a Rich progress bar for batch processing."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
        console=console,
    )


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
@click.option(
    "-t",
    "--threshold",
    type=click.FloatRange(0.0, 1.0),
    default=0.8,
    help="Confidence cutoff for auto-accept (0.0-1.0, default 0.8).",
)
@click.option(
    "--resume/--no-resume",
    default=True,
    help="Skip files already in output-dir (default: --resume).",
)
def match(
    path: Path,
    output_dir: Path | None,
    quiet: bool,
    threshold: float,
    resume: bool,
) -> None:
    """Match EPUB metadata against Open Library and write corrected copies."""
    console = Console()

    if output_dir is None:
        output_dir = Path("bookery-output")

    provider = _create_provider()
    review = ReviewSession(
        console=console,
        quiet=quiet,
        threshold=threshold,
        lookup_fn=provider.lookup_by_url,
    )

    epubs = _find_epubs(path)
    if not epubs:
        console.print("[yellow]No EPUB files found.[/yellow]")
        return

    # Resume: filter out already-processed files
    if resume and output_dir.exists():
        original_count = len(epubs)
        epubs = [e for e in epubs if not _is_already_processed(e, output_dir)]
        skipped_count = original_count - len(epubs)
        if skipped_count:
            console.print(
                f"[dim]Skipping {skipped_count} already-processed "
                f"file{'s' if skipped_count != 1 else ''}.[/dim]"
            )
        if not epubs:
            console.print("[green]All files already processed.[/green]")
            return

    total = len(epubs)
    matched = 0
    skipped = 0
    errors = 0

    progress = _make_progress(console)
    task_id = progress.add_task("Matching", total=total)
    progress.start()

    for epub_path in epubs:
        progress.update(task_id, description=epub_path.name)

        # Pause progress bar for interactive output
        if not quiet:
            progress.stop()
            console.print(
                f"\n[bold][{progress.tasks[task_id].completed + 1}/{total}] "
                f"Processing:[/bold] {epub_path.name}"
            )

        try:
            extracted = read_epub_metadata(epub_path)
        except EpubReadError as exc:
            if not quiet:
                console.print(f"  [red]Error reading:[/red] {exc}")
            errors += 1
            progress.advance(task_id)
            if not quiet:
                progress.start()
            continue

        # Normalize mangled metadata for better search queries
        norm_result = normalize_metadata(extracted)
        if not quiet and norm_result.was_modified:
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
            if not quiet:
                console.print("  [yellow]No candidates found.[/yellow]")
            skipped += 1
            progress.advance(task_id)
            if not quiet:
                progress.start()
            continue

        selected = review.review(extracted, candidates)
        if selected is None:
            skipped += 1
            progress.advance(task_id)
            if not quiet:
                progress.start()
            continue

        try:
            write_result = apply_metadata_safely(epub_path, selected, output_dir)
            if write_result.success:
                if not quiet:
                    console.print(f"  [green]Written:[/green] {write_result.path}")
                matched += 1
            else:
                if not quiet:
                    console.print(
                        f"  [red]Verification failed:[/red] {write_result.error}"
                    )
                errors += 1
        except OSError as exc:
            if not quiet:
                console.print(f"  [red]Error writing:[/red] {exc}")
            errors += 1

        progress.advance(task_id)
        if not quiet:
            progress.start()

    progress.stop()

    # Summary
    parts = []
    if matched:
        parts.append(f"[green]{matched} matched[/green]")
    if skipped:
        parts.append(f"[yellow]{skipped} skipped[/yellow]")
    if errors:
        parts.append(f"[red]{errors} error{'s' if errors != 1 else ''}[/red]")

    console.print(f"\nDone: {', '.join(parts)}")
