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

from bookery.cli._match_helpers import build_metadata_provider
from bookery.cli.options import auto_accept_option, threshold_option
from bookery.cli.review import ReviewSession
from bookery.core.config import get_library_root
from bookery.core.pathformat import is_processed
from bookery.core.pipeline import match_one

logger = logging.getLogger(__name__)


def _create_provider(*, use_cache: bool = True):
    """Create the default metadata provider (Open Library), optionally cached."""
    return build_metadata_provider(use_cache=use_cache)


def _find_epubs(path: Path) -> list[Path]:
    """Find EPUB files at the given path (single file or directory)."""
    if path.is_file():
        return [path]
    return sorted(path.rglob("*.epub"))


def _is_already_processed(epub_path: Path, output_dir: Path) -> bool:
    """Check if an EPUB has already been written to the output directory.

    Checks the .bookery-processed manifest first (for organized output),
    then falls back to searching recursively for the original filename
    or collision-suffixed variants.
    """
    if is_processed(output_dir, epub_path.name):
        return True
    # Fallback: search for the original filename in case of pre-manifest output
    stem = epub_path.stem
    suffix = epub_path.suffix
    pattern = re.compile(re.escape(stem) + r"(_\d+)?" + re.escape(suffix))
    return any(pattern.fullmatch(child.name) for child in output_dir.rglob(f"*{suffix}"))


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
    help="Directory for modified copies (default: configured library_root).",
)
@auto_accept_option
@threshold_option
@click.option(
    "--resume/--no-resume",
    default=True,
    help="Skip files already in output-dir (default: --resume).",
)
@click.option(
    "--no-cache",
    "no_cache",
    is_flag=True,
    help="Skip the metadata response cache and force fresh provider lookups.",
)
def match(
    path: Path,
    output_dir: Path | None,
    auto_accept: bool,
    threshold: float,
    resume: bool,
    no_cache: bool,
) -> None:
    """Match EPUB metadata against Open Library and write corrected copies."""
    console = Console()

    if output_dir is None:
        output_dir = get_library_root()

    provider = _create_provider(use_cache=not no_cache)
    review = ReviewSession(
        console=console,
        quiet=auto_accept,
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
        if not auto_accept:
            progress.stop()
            console.print(
                f"\n[bold][{progress.tasks[task_id].completed + 1}/{total}] "
                f"Processing:[/bold] {epub_path.name}"
            )

        result = match_one(epub_path, provider, review, output_dir)

        # Display normalization info in interactive mode
        if not auto_accept and result.normalization and result.normalization.was_modified:
            console.print(
                f"  [dim]Normalized title:[/dim] {result.normalization.normalized.title}"
            )
            if result.normalization.normalized.authors != result.normalization.original.authors:
                console.print(
                    f"  [dim]Detected author:[/dim] {result.normalization.normalized.author}"
                )

        if result.status == "matched":
            if not auto_accept:
                rel_path = result.output_path.relative_to(output_dir) if result.output_path else ""
                console.print(f"  [green]Written:[/green] {rel_path}")
            matched += 1
        elif result.status == "skipped":
            if not auto_accept and result.error is None:
                # Only show "No candidates" if it wasn't a user skip (review returns None)
                pass
            skipped += 1
        elif result.status == "error":
            if not auto_accept:
                console.print(f"  [red]Error:[/red] {result.error}")
            errors += 1

        progress.advance(task_id)
        if not auto_accept:
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
