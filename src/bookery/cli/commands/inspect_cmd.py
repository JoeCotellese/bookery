# ABOUTME: The `bookery inspect` command for viewing EPUB metadata.
# ABOUTME: Shows extracted metadata for a single EPUB file.

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from bookery.formats.epub import EpubReadError, read_epub_metadata

console = Console()


@click.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
def inspect(path: Path) -> None:
    """Show metadata extracted from an EPUB file."""
    try:
        meta = read_epub_metadata(path)
    except EpubReadError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1) from exc

    table = Table(title=str(path.name), show_header=False, pad_edge=False)
    table.add_column("Field", style="bold")
    table.add_column("Value")

    table.add_row("Title", meta.title)
    table.add_row("Author", meta.author or "[dim]unknown[/dim]")
    table.add_row("Language", meta.language or "[dim]unknown[/dim]")
    table.add_row("Publisher", meta.publisher or "[dim]unknown[/dim]")
    table.add_row("ISBN", meta.isbn or "[dim]none[/dim]")
    table.add_row("Description", meta.description or "[dim]none[/dim]")
    table.add_row("Series", meta.series or "[dim]none[/dim]")
    if meta.series_index is not None:
        table.add_row("Series Index", str(meta.series_index))
    table.add_row("Cover", "yes" if meta.has_cover else "no")
    if meta.identifiers:
        ids_str = ", ".join(f"{k}={v}" for k, v in meta.identifiers.items())
        table.add_row("Identifiers", ids_str)

    console.print(table)
