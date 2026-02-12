# ABOUTME: The `bookery search` command for full-text search of the catalog.
# ABOUTME: Searches title, author, and description using SQLite FTS5.

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from bookery.cli.options import db_option
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import DEFAULT_DB_PATH, open_library

console = Console()


@click.command("search")
@click.argument("query")
@db_option
def search(query: str, db_path: Path | None) -> None:
    """Search the library catalog by title, author, or description."""
    conn = open_library(db_path or DEFAULT_DB_PATH)
    catalog = LibraryCatalog(conn)

    results = catalog.search(query)

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        conn.close()
        return

    table = Table()
    table.add_column("ID", style="dim", width=4)
    table.add_column("Title", style="bold")
    table.add_column("Author")
    table.add_column("Lang", width=5)

    for record in results:
        table.add_row(
            str(record.id),
            record.metadata.title,
            record.metadata.author or "[dim]unknown[/dim]",
            record.metadata.language or "?",
        )

    console.print(table)
    console.print(f"\n[dim]{len(results)} result(s)[/dim]")
    conn.close()
