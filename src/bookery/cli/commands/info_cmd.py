# ABOUTME: The `bookery info` command for displaying detailed book metadata.
# ABOUTME: Shows all fields for a single cataloged book by ID.

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from bookery.cli.options import db_option
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import DEFAULT_DB_PATH, open_library

console = Console()  # TODO: move Console() inside command for testability


@click.command("info")
@click.argument("book_id", type=int)
@db_option
def info(book_id: int, db_path: Path | None) -> None:
    """Show detailed metadata for a book by ID."""
    # TODO: wrap conn in try-finally or context manager to prevent leak on exception
    conn = open_library(db_path or DEFAULT_DB_PATH)
    catalog = LibraryCatalog(conn)

    record = catalog.get_by_id(book_id)

    if record is None:
        console.print(f"[red]Book {book_id} not found.[/red]")
        conn.close()
        raise SystemExit(1)

    meta = record.metadata
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("Field", style="bold", width=14)
    table.add_column("Value")

    table.add_row("ID", str(record.id))
    table.add_row("Title", meta.title)
    table.add_row("Author", meta.author or "unknown")
    if meta.author_sort:
        table.add_row("Author Sort", meta.author_sort)
    table.add_row("Language", meta.language or "?")
    if meta.publisher:
        table.add_row("Publisher", meta.publisher)
    if meta.isbn:
        table.add_row("ISBN", meta.isbn)
    if meta.description:
        table.add_row("Description", meta.description)
    if meta.series:
        idx = meta.series_index
        series_str = f"{meta.series} #{idx:g}" if idx is not None else meta.series
        table.add_row("Series", series_str)
    tags = catalog.get_tags_for_book(book_id)
    if tags:
        table.add_row("Tags", ", ".join(tags))
    table.add_row("Source", str(record.source_path))
    if record.output_path:
        table.add_row("Output", str(record.output_path))
    table.add_row("Hash", record.file_hash)
    table.add_row("Added", record.date_added)
    table.add_row("Modified", record.date_modified)

    console.print(table)
    conn.close()
