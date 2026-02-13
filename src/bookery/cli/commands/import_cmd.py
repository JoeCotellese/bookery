# ABOUTME: The `bookery import` command for scanning and cataloging EPUBs.
# ABOUTME: Walks a directory, extracts metadata, and stores records in the library DB.

from pathlib import Path

import click
from rich.console import Console

from bookery.cli.options import db_option
from bookery.core.importer import MatchResult, import_books
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import DEFAULT_DB_PATH, open_library
from bookery.metadata.types import BookMetadata

console = Console()  # TODO: move Console() inside command for testability


def _find_epubs(directory: Path) -> list[Path]:
    """Recursively find all .epub files in a directory."""
    return sorted(directory.rglob("*.epub"))


def _build_match_fn(
    output_dir: Path, quiet: bool, threshold: float,
) -> "MatchResult | None":
    """Build a match callback that runs the full metadata pipeline.

    Imports match-pipeline dependencies lazily so the import command
    doesn't pay for them when --match is not used.
    """
    from bookery.cli.review import ReviewSession
    from bookery.core.pipeline import apply_metadata_safely
    from bookery.metadata.http import BookeryHttpClient
    from bookery.metadata.normalizer import normalize_metadata
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
        norm_result = normalize_metadata(extracted)
        if not quiet and norm_result.was_modified:
            console.print(
                f"  [dim]Normalized:[/dim] {norm_result.normalized.title}"
            )
        search_meta = norm_result.normalized

        candidates = []
        if search_meta.isbn:
            candidates = provider.search_by_isbn(search_meta.isbn)
        if not candidates:
            candidates = provider.search_by_title_author(
                search_meta.title, search_meta.author or None,
            )

        if not candidates:
            if not quiet:
                console.print("  [yellow]No candidates found.[/yellow]")
            return None

        selected = review.review(extracted, candidates)
        if selected is None:
            return None

        write_result = apply_metadata_safely(epub_path, selected, output_dir)
        if write_result.success:
            if not quiet:
                console.print(
                    f"  [green]Written:[/green] {write_result.path}"
                )
            return MatchResult(
                metadata=selected, output_path=write_result.path,
            )

        if not quiet:
            console.print(
                f"  [red]Write failed:[/red] {write_result.error}"
            )
        return None

    return match_fn


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
def import_command(
    directory: Path,
    db_path: Path | None,
    do_match: bool,
    output_dir: Path | None,
    quiet: bool,
    threshold: float,
) -> None:
    """Scan a directory for EPUB files and catalog them in the library."""
    epub_files = _find_epubs(directory)

    if not epub_files:
        console.print(f"[yellow]No EPUB files found in {directory}[/yellow]")
        return

    console.print(f"Found [bold]{len(epub_files)}[/bold] EPUB file(s)\n")

    # TODO: wrap conn in try-finally or context manager to prevent leak on exception
    conn = open_library(db_path or DEFAULT_DB_PATH)
    catalog = LibraryCatalog(conn)

    match_fn = None
    if do_match:
        match_fn = _build_match_fn(
            output_dir=output_dir or Path("bookery-output"),
            quiet=quiet,
            threshold=threshold,
        )

    result = import_books(epub_files, catalog, match_fn=match_fn)

    # Summary
    parts = []
    if result.added:
        parts.append(f"[green]{result.added} added[/green]")
    if result.skipped:
        parts.append(f"[yellow]{result.skipped} skipped[/yellow]")
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
