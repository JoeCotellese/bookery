# ABOUTME: The `bookery convert` command for MOBI-to-EPUB conversion.
# ABOUTME: Converts MOBI files to EPUB so they can flow through the existing pipeline.

import logging
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
from bookery.core.converter import convert_one
from bookery.core.pipeline import match_one

logger = logging.getLogger(__name__)


def _create_provider():
    """Create the default metadata provider (Open Library) with caching."""
    return build_metadata_provider()


def _find_mobis(path: Path) -> list[Path]:
    """Find MOBI files at the given path (single file or directory)."""
    if path.is_file():
        if path.suffix.lower() == ".mobi":
            return [path]
        return []
    return sorted(path.rglob("*.mobi"))


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
    help="Directory for converted EPUBs (default: configured library_root).",
)
@click.option(
    "--match/--no-match",
    "do_match",
    default=False,
    help="Chain into metadata matching after conversion (default: --no-match).",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite existing output files.",
)
@auto_accept_option
@threshold_option
def convert(
    path: Path,
    output_dir: Path | None,
    do_match: bool,
    force: bool,
    auto_accept: bool,
    threshold: float,
) -> None:
    """Convert MOBI files to EPUB format."""
    console = Console()

    if output_dir is None:
        output_dir = get_library_root()

    mobis = _find_mobis(path)
    if not mobis:
        console.print("[yellow]No MOBI files found.[/yellow]")
        return

    # Set up match pipeline if requested
    provider = None
    review = None
    if do_match:
        provider = _create_provider()
        review = ReviewSession(
            console=console,
            quiet=auto_accept,
            threshold=threshold,
            lookup_fn=provider.lookup_by_url,
        )

    total = len(mobis)
    converted = 0
    skipped = 0
    errors = 0
    matched_count = 0

    progress = _make_progress(console)
    task_id = progress.add_task("Converting", total=total)
    progress.start()

    for mobi_path in mobis:
        progress.update(task_id, description=mobi_path.name)

        result = convert_one(mobi_path, output_dir, force=force)

        if result.skipped:
            skipped += 1
        elif result.success and result.epub_path and result.epub_path.exists():
            converted += 1

            # Chain into match pipeline if requested
            if do_match and provider and review and result.epub_path:
                match_result = match_one(result.epub_path, provider, review, output_dir)
                if match_result.status == "matched":
                    matched_count += 1
        elif not result.success:
            errors += 1

        progress.advance(task_id)

    progress.stop()

    # Summary
    parts = []
    if converted:
        parts.append(f"[green]{converted} converted[/green]")
    if matched_count:
        parts.append(f"[green]{matched_count} matched[/green]")
    if skipped:
        parts.append(f"[yellow]{skipped} skipped[/yellow]")
    if errors:
        parts.append(f"[red]{errors} error{'s' if errors != 1 else ''}[/red]")

    console.print(f"\nDone: {', '.join(parts)}")
