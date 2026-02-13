# ABOUTME: The `bookery ls` command for listing cataloged books.
# ABOUTME: Displays a Rich table of all books in the library database.

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from bookery.cli.options import db_option
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import DEFAULT_DB_PATH, open_library

console = Console()  # TODO: move Console() inside command for testability


@click.command("ls")
@db_option
@click.option(
    "--series",
    "series_filter",
    default=None,
    help="Filter by series name.",
)
@click.option(
    "--tag",
    "tag_filter",
    default=None,
    help="Filter by tag name.",
)
def ls(db_path: Path | None, series_filter: str | None, tag_filter: str | None) -> None:
    """List all books in the library catalog."""
    # TODO: wrap conn in try-finally or context manager to prevent leak on exception
    conn = open_library(db_path or DEFAULT_DB_PATH)
    catalog = LibraryCatalog(conn)

    if tag_filter:
        try:
            records = catalog.get_books_by_tag(tag_filter)
        except ValueError as exc:
            console.print(f"[red]Tag '{tag_filter}' not found.[/red]")
            conn.close()
            raise SystemExit(1) from exc
    elif series_filter:
        records = catalog.list_by_series(series_filter)
    else:
        records = catalog.list_all()

    if not records:
        console.print("[yellow]No books in the library.[/yellow]")
        conn.close()
        return

    table = Table()
    table.add_column("ID", style="dim", width=4)
    table.add_column("Title", style="bold")
    table.add_column("Author")
    table.add_column("Series")
    table.add_column("Lang", width=5)

    for record in records:
        series_display = ""
        if record.metadata.series:
            idx = record.metadata.series_index
            if idx is not None:
                series_display = f"{record.metadata.series} #{idx:g}"
            else:
                series_display = record.metadata.series

        table.add_row(
            str(record.id),
            record.metadata.title,
            record.metadata.author or "[dim]unknown[/dim]",
            series_display,
            record.metadata.language or "?",
        )

    console.print(table)
    console.print(f"\n[dim]{len(records)} book(s)[/dim]")
    conn.close()
