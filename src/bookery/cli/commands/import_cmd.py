# ABOUTME: The `bookery import` command for scanning and cataloging EPUBs.
# ABOUTME: Walks a directory, extracts metadata, and stores records in the library DB.

from pathlib import Path

import click
from rich.console import Console

from bookery.cli.options import db_option
from bookery.core.dedup import filter_redundant_mobis
from bookery.core.importer import ImportResult, MatchFn, MatchResult, ProgressFn, import_books
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import DEFAULT_DB_PATH, open_library
from bookery.metadata.types import BookMetadata

console = Console()  # TODO: move Console() inside command for testability


def _find_epubs(directory: Path) -> list[Path]:
    """Recursively find all .epub files in a directory."""
    return sorted(directory.rglob("*.epub"))


def _find_mobis(directory: Path) -> list[Path]:
    """Recursively find all .mobi files in a directory."""
    return sorted(directory.rglob("*.mobi"))


def _convert_mobis(
    mobi_files: list[Path],
    epub_files: list[Path],
    output_dir: Path | None,
) -> list[Path]:
    """Convert MOBI files to EPUB and extend the epub_files list.

    Lazy-imports convert_one so the import command doesn't pay for
    converter dependencies when --convert is not used.
    """
    from bookery.core.converter import convert_one

    resolved_output = output_dir or Path("bookery-output")
    total = len(mobi_files)
    converted = 0
    skipped = 0
    failed = 0

    console.print(f"Converting [bold]{total}[/bold] MOBI file(s)…\n")

    for i, mobi_path in enumerate(mobi_files, 1):
        console.print(
            f"  [{i}/{total}] {mobi_path.name}… ", end="",
        )
        result = convert_one(mobi_path, resolved_output, force=False)
        if result.skipped and result.epub_path:
            epub_files.append(result.epub_path)
            skipped += 1
            console.print("[dim]skipped (already converted)[/dim]")
        elif result.skipped:
            # Manifest says processed but EPUB path not recoverable
            skipped += 1
            console.print("[dim]skipped (already converted, path unknown)[/dim]")
        elif result.success and result.epub_path:
            epub_files.append(result.epub_path)
            converted += 1
            console.print("[green]done[/green]")
        else:
            failed += 1
            console.print(f"[red]failed:[/red] {result.error}")

    # Summary line
    parts = []
    if converted:
        parts.append(f"[green]{converted} converted[/green]")
    if skipped:
        parts.append(f"[dim]{skipped} skipped[/dim]")
    if failed:
        parts.append(f"[red]{failed} failed[/red]")
    console.print(f"\nConversion: {', '.join(parts)}")
    console.print(
        f"Converted [bold]{converted + skipped}[/bold] of "
        f"[bold]{total}[/bold] MOBI file(s)\n",
    )
    return epub_files


def _build_match_fn(
    output_dir: Path, quiet: bool, threshold: float,
) -> MatchFn:
    """Build a match callback that runs the full metadata pipeline.

    Imports match-pipeline dependencies lazily so the import command
    doesn't pay for them when --match is not used.
    """
    from bookery.cli.review import ReviewSession
    from bookery.core.pipeline import match_one
    from bookery.metadata.http import BookeryHttpClient
    from bookery.metadata.openlibrary import OpenLibraryProvider

    http_client = BookeryHttpClient()
    provider = OpenLibraryProvider(http_client=http_client)
    review = ReviewSession(
        console=console,
        quiet=quiet,
        threshold=threshold,
        lookup_fn=provider.lookup_by_url,
    )

    def match_fn(
        extracted: BookMetadata, epub_path: Path,
    ) -> MatchResult | None:
        result = match_one(epub_path, provider, review, output_dir)

        if not quiet and result.normalization and result.normalization.was_modified:
            console.print(
                f"  [dim]Normalized:[/dim] {result.normalization.normalized.title}"
            )

        if result.status == "matched" and result.metadata is not None:
            if not quiet:
                console.print(
                    f"  [green]Written:[/green] {result.output_path}"
                )
            return MatchResult(
                metadata=result.metadata, output_path=result.output_path,
            )

        if result.status == "error" and not quiet:
            console.print(
                f"  [red]Write failed:[/red] {result.error}"
            )

        return None

    return match_fn


def _format_skip_breakdown(result: ImportResult) -> str:
    """Format a skip count with breakdown by reason."""
    if result.skipped == 0:
        return ""

    parts = []
    if result.skipped_hash:
        parts.append(f"{result.skipped_hash} hash")
    if result.skipped_metadata:
        # Break metadata skips down by specific reason
        reason_counts: dict[str, int] = {}
        for detail in result.skip_details:
            if detail.reason in ("isbn", "title_author"):
                label = detail.reason.replace("_", "+")
                reason_counts[label] = reason_counts.get(label, 0) + 1
        parts.extend(f"{count} {reason}" for reason, count in reason_counts.items())

    breakdown = f" ({', '.join(parts)})" if parts else ""
    return f"{result.skipped} skipped{breakdown}"


def _build_progress_fn() -> ProgressFn:
    """Build a per-file progress callback for Rich console output."""

    def on_progress(
        path: Path,
        title: str,
        author: str,
        status: str,
        reason: str | None,
        existing_id: int | None,
    ) -> None:
        label = f"{title} — {author}" if title and author else path.name
        if status == "added":
            console.print(f"  [green]✓[/green] {label}")
        elif status == "skipped" and reason:
            reason_label = reason.replace("_", "+")
            id_suffix = f", #{existing_id}" if existing_id else ""
            console.print(
                f"  [yellow]⊘[/yellow] {label} — "
                f"[dim]skipped (duplicate: {reason_label}{id_suffix})[/dim]"
            )
        elif status == "forced" and reason:
            reason_label = reason.replace("_", "+")
            id_suffix = f", #{existing_id}" if existing_id else ""
            console.print(
                f"  [yellow]⚠[/yellow] {label} — "
                f"[dim]imported (duplicate: {reason_label}{id_suffix})[/dim]"
            )
        elif status == "error":
            console.print(f"  [red]✗[/red] {path.name} — [red]{reason}[/red]")

    return on_progress



@click.command("import")
@click.argument(
    "directory",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@db_option
@click.option(
    "--match/--no-match",
    "do_match",
    default=False,
    help="Run metadata matching pipeline before cataloging.",
)
@click.option(
    "-o", "--output-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Directory for modified copies (default: ./bookery-output).",
)
@click.option(
    "-q", "--quiet",
    is_flag=True,
    default=False,
    help="Auto-accept high-confidence matches without prompting.",
)
@click.option(
    "-t", "--threshold",
    type=click.FloatRange(0.0, 1.0),
    default=0.8,
    help="Confidence cutoff for auto-accept (0.0-1.0, default 0.8).",
)
@click.option(
    "--convert/--no-convert",
    "do_convert",
    default=False,
    help="Convert MOBI files to EPUB before importing.",
)
@click.option(
    "--force-duplicates",
    is_flag=True,
    default=False,
    help="Import metadata duplicates (same ISBN or title+author) instead of skipping.",
)
def import_command(
    directory: Path,
    db_path: Path | None,
    do_match: bool,
    output_dir: Path | None,
    quiet: bool,
    threshold: float,
    do_convert: bool,
    force_duplicates: bool,
) -> None:
    """Scan a directory for EPUB files and catalog them in the library."""
    epub_files = _find_epubs(directory)

    if do_convert:
        mobi_files = _find_mobis(directory)
        if mobi_files:
            mobi_files, dedup_skipped = filter_redundant_mobis(
                mobi_files, epub_files,
            )
            if dedup_skipped:
                console.print(
                    f"Skipped {len(dedup_skipped)} MOBI file(s) "
                    f"— EPUB exists in directory\n",
                )
        if mobi_files:
            epub_files = _convert_mobis(mobi_files, epub_files, output_dir)

    if not epub_files:
        if do_convert:
            console.print(
                f"[yellow]No EPUB or MOBI files found in {directory}[/yellow]",
            )
        else:
            console.print(
                f"[yellow]No EPUB files found in {directory}[/yellow]",
            )
        return

    console.print(f"Found [bold]{len(epub_files)}[/bold] EPUB file(s)\n")

    # TODO: wrap conn in try-finally or context manager to prevent leak on exception
    conn = open_library(db_path or DEFAULT_DB_PATH)
    catalog = LibraryCatalog(conn)

    match_fn: MatchFn | None = None
    if do_match:
        match_fn = _build_match_fn(
            output_dir=output_dir or Path("bookery-output"),
            quiet=quiet,
            threshold=threshold,
        )

    on_progress = _build_progress_fn()

    result = import_books(
        epub_files, catalog,
        match_fn=match_fn,
        force_duplicates=force_duplicates,
        on_progress=on_progress,
    )

    # Summary
    console.print()  # blank line before summary
    parts = []
    if result.added:
        parts.append(f"[green]{result.added} added[/green]")
    if result.skipped:
        parts.append(f"[yellow]{_format_skip_breakdown(result)}[/yellow]")
    if result.forced:
        parts.append(f"[yellow]{result.forced} forced[/yellow]")
    if result.errors:
        parts.append(f"[red]{result.errors} error(s)[/red]")

    console.print(", ".join(parts))

    if result.error_details:
        console.print(
            f"\n[yellow]{result.errors} file(s) could not be read:[/yellow]"
        )
        for path, msg in result.error_details:
            console.print(f"  [dim]{path.name}:[/dim] {msg}")

    conn.close()
