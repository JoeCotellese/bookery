# ABOUTME: The `bookery tag` command group for managing book tags.
# ABOUTME: Provides add, rm, and ls subcommands for tagging operations.

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from bookery.cli.options import db_option
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import DEFAULT_DB_PATH, open_library

console = Console()  # TODO: move Console() inside command for testability


@click.group("tag")
def tag() -> None:
    """Manage book tags."""


@tag.command("add")
@click.argument("book_id", type=int)
@click.argument("tag_name")
@db_option
def tag_add(book_id: int, tag_name: str, db_path: Path | None) -> None:
    """Add a tag to a book."""
    # TODO: wrap conn in try-finally or context manager to prevent leak on exception
    conn = open_library(db_path or DEFAULT_DB_PATH)
    catalog = LibraryCatalog(conn)

    record = catalog.get_by_id(book_id)
    if record is None:
        console.print(f"[red]Book {book_id} not found.[/red]")
        conn.close()
        raise SystemExit(1)

    try:
        catalog.add_tag(book_id, tag_name)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        conn.close()
        raise SystemExit(1) from exc

    console.print(f"Tagged [bold]{record.metadata.title}[/bold] with [cyan]{tag_name}[/cyan].")
    conn.close()


@tag.command("rm")
@click.argument("book_id", type=int)
@click.argument("tag_name")
@db_option
def tag_rm(book_id: int, tag_name: str, db_path: Path | None) -> None:
    """Remove a tag from a book."""
    # TODO: wrap conn in try-finally or context manager to prevent leak on exception
    conn = open_library(db_path or DEFAULT_DB_PATH)
    catalog = LibraryCatalog(conn)

    try:
        catalog.remove_tag(book_id, tag_name)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        conn.close()
        raise SystemExit(1) from exc

    console.print(f"Removed tag [cyan]{tag_name}[/cyan] from book {book_id}.")
    conn.close()


@tag.command("ls")
@db_option
def tag_ls(db_path: Path | None) -> None:
    """List all tags with book counts."""
    # TODO: wrap conn in try-finally or context manager to prevent leak on exception
    conn = open_library(db_path or DEFAULT_DB_PATH)
    catalog = LibraryCatalog(conn)

    tags = catalog.list_tags()

    if not tags:
        console.print("[yellow]No tags in the library.[/yellow]")
        conn.close()
        return

    table = Table()
    table.add_column("Tag", style="cyan")
    table.add_column("Books", style="dim", justify="right")

    for name, count in tags:
        table.add_row(name, str(count))

    console.print(table)
    conn.close()
