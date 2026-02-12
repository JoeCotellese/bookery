# ABOUTME: The `bookery import` command for scanning and cataloging EPUBs.
# ABOUTME: Walks a directory, extracts metadata, and stores records in the library DB.

from pathlib import Path

import click
from rich.console import Console

from bookery.core.importer import import_books
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import DEFAULT_DB_PATH, open_library

console = Console()


def _find_epubs(directory: Path) -> list[Path]:
    """Recursively find all .epub files in a directory."""
    return sorted(directory.rglob("*.epub"))


@click.command("import")
@click.argument(
    "directory",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--db",
    "db_path",
    type=click.Path(path_type=Path),
    default=None,
    help=f"Path to library database (default: {DEFAULT_DB_PATH})",
)
def import_command(directory: Path, db_path: Path | None) -> None:
    """Scan a directory for EPUB files and catalog them in the library."""
    epub_files = _find_epubs(directory)

    if not epub_files:
        console.print(f"[yellow]No EPUB files found in {directory}[/yellow]")
        return

    console.print(f"Found [bold]{len(epub_files)}[/bold] EPUB file(s)\n")

    conn = open_library(db_path or DEFAULT_DB_PATH)
    catalog = LibraryCatalog(conn)

    result = import_books(epub_files, catalog)

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
