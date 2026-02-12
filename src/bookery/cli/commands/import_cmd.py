# ABOUTME: The `bookery import` command for scanning and cataloging EPUBs.
# ABOUTME: Walks a directory, extracts metadata, and displays results.

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from bookery.formats.epub import EpubReadError, read_epub_metadata

console = Console()


def _find_epubs(directory: Path) -> list[Path]:
    """Recursively find all .epub files in a directory."""
    return sorted(directory.rglob("*.epub"))


@click.command("import")
@click.argument("directory", type=click.Path(exists=True, file_okay=False, path_type=Path))
def import_books(directory: Path) -> None:
    """Scan a directory for EPUB files and display their metadata."""
    epub_files = _find_epubs(directory)

    if not epub_files:
        console.print(f"[yellow]No EPUB files found in {directory}[/yellow]")
        return

    console.print(f"Found [bold]{len(epub_files)}[/bold] EPUB file(s)\n")

    table = Table()
    table.add_column("#", style="dim", width=4)
    table.add_column("Title", style="bold")
    table.add_column("Author")
    table.add_column("Language", width=5)
    table.add_column("File")

    errors: list[tuple[Path, str]] = []

    for i, epub_path in enumerate(epub_files, 1):
        try:
            meta = read_epub_metadata(epub_path)
            table.add_row(
                str(i),
                meta.title,
                meta.author or "[dim]unknown[/dim]",
                meta.language or "?",
                epub_path.name,
            )
        except EpubReadError as exc:
            errors.append((epub_path, str(exc)))
            table.add_row(
                str(i),
                "[red]ERROR[/red]",
                "",
                "",
                epub_path.name,
            )

    console.print(table)

    if errors:
        console.print(f"\n[yellow]{len(errors)} file(s) could not be read:[/yellow]")
        for path, msg in errors:
            console.print(f"  [dim]{path.name}:[/dim] {msg}")

    console.print(f"\n[green]{len(epub_files) - len(errors)}[/green] scanned successfully.")
