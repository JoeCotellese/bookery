# ABOUTME: The `bookery collections` command group for managing book collections.
# ABOUTME: Provides create, add-books, remove-books, ls, show, rm, rename subcommands.

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from bookery.cli.options import db_option, resolve_db_path
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library

console = Console()


@click.group("collections")
def collections() -> None:
    """Manage book collections (manual curation)."""


@collections.command("create")
@click.argument("name")
@click.option("--description", "-d", help="Optional description for the collection.")
@db_option
def collections_create(name: str, description: str | None, db_path: Path | None) -> None:
    """Create a new collection."""
    conn = open_library(resolve_db_path(db_path))
    catalog = LibraryCatalog(conn)

    try:
        collection_id = catalog.create_collection(name, description)
    except Exception as exc:
        console.print(f"[red]Failed to create collection: {exc}[/red]")
        conn.close()
        raise SystemExit(1) from exc

    console.print(f"Created collection [bold]{name}[/bold] (ID: {collection_id}).")
    conn.close()


@collections.command("add-books")
@click.argument("collection_id", type=int)
@click.argument("book_ids", nargs=-1, type=int, required=True)
@db_option
def collections_add_books(
    collection_id: int, book_ids: tuple[int, ...], db_path: Path | None
) -> None:
    """Add books to a collection by their IDs."""
    conn = open_library(resolve_db_path(db_path))
    catalog = LibraryCatalog(conn)

    # Verify collection exists
    collection = catalog.get_collection_by_id(collection_id)
    if collection is None:
        console.print(f"[red]Collection {collection_id} not found.[/red]")
        conn.close()
        raise SystemExit(1)

    book_ids_list = list(book_ids)

    try:
        catalog.add_books_to_collection(collection_id, book_ids_list)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        conn.close()
        raise SystemExit(1) from exc

    console.print(
        f"Added [bold]{len(book_ids_list)}[/bold] book(s) to collection "
        f"[cyan]{collection['name']}[/cyan]."
    )
    conn.close()


@collections.command("remove-books")
@click.argument("collection_id", type=int)
@click.argument("book_ids", nargs=-1, type=int, required=True)
@db_option
def collections_remove_books(
    collection_id: int, book_ids: tuple[int, ...], db_path: Path | None
) -> None:
    """Remove books from a collection by their IDs."""
    conn = open_library(resolve_db_path(db_path))
    catalog = LibraryCatalog(conn)

    # Verify collection exists
    collection = catalog.get_collection_by_id(collection_id)
    if collection is None:
        console.print(f"[red]Collection {collection_id} not found.[/red]")
        conn.close()
        raise SystemExit(1)

    book_ids_list = list(book_ids)

    try:
        catalog.remove_books_from_collection(collection_id, book_ids_list)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        conn.close()
        raise SystemExit(1) from exc

    console.print(
        f"Removed [bold]{len(book_ids_list)}[/bold] book(s) from collection "
        f"[cyan]{collection['name']}[/cyan]."
    )
    conn.close()


@collections.command("ls")
@db_option
def collections_ls(db_path: Path | None) -> None:
    """List all collections with book counts."""
    conn = open_library(resolve_db_path(db_path))
    catalog = LibraryCatalog(conn)

    collections_list = catalog.list_collections()

    if not collections_list:
        console.print("[yellow]No collections in the library.[/yellow]")
        conn.close()
        return

    table = Table()
    table.add_column("ID", style="dim", width=6)
    table.add_column("Name", style="cyan")
    table.add_column("Books", style="dim", justify="right")
    table.add_column("Description")

    for coll in collections_list:
        desc = str(coll.get("description") or "")
        table.add_row(
            str(coll["id"]),
            str(coll["name"]),
            str(coll["book_count"]),
            desc,
        )

    console.print(table)
    conn.close()


@collections.command("show")
@click.argument("collection_id", type=int)
@db_option
def collections_show(collection_id: int, db_path: Path | None) -> None:
    """Show collection details and list books in it."""
    conn = open_library(resolve_db_path(db_path))
    catalog = LibraryCatalog(conn)

    collection = catalog.get_collection_by_id(collection_id)
    if collection is None:
        console.print(f"[red]Collection {collection_id} not found.[/red]")
        conn.close()
        raise SystemExit(1)

    console.print(f"[bold]{collection['name']}[/bold] (ID: {collection_id})")
    if collection.get("description"):
        console.print(f"[dim]{collection['description']}[/dim]")
    console.print()

    books = catalog.get_collection_books(collection_id)

    if not books:
        console.print("[yellow]No books in this collection.[/yellow]")
        conn.close()
        return

    table = Table()
    table.add_column("ID", style="dim", width=6)
    table.add_column("Title", style="bold")
    table.add_column("Author(s)")

    for book in books:
        authors = ", ".join(book.metadata.authors) if book.metadata.authors else "Unknown"
        table.add_row(str(book.id), book.metadata.title, authors)

    console.print(f"[bold]{len(books)} book(s):[/bold]")
    console.print(table)
    conn.close()


@collections.command("rm")
@click.argument("collection_id", type=int)
@click.confirmation_option(prompt="Are you sure you want to delete this collection?")
@db_option
def collections_rm(collection_id: int, db_path: Path | None) -> None:
    """Delete a collection (books are not deleted)."""
    conn = open_library(resolve_db_path(db_path))
    catalog = LibraryCatalog(conn)

    collection = catalog.get_collection_by_id(collection_id)
    if collection is None:
        console.print(f"[red]Collection {collection_id} not found.[/red]")
        conn.close()
        raise SystemExit(1)

    try:
        catalog.delete_collection(collection_id)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        conn.close()
        raise SystemExit(1) from exc

    console.print(f"Deleted collection [bold]{collection['name']}[/bold].")
    conn.close()


@collections.command("rename")
@click.argument("collection_id", type=int)
@click.argument("new_name")
@db_option
def collections_rename(collection_id: int, new_name: str, db_path: Path | None) -> None:
    """Rename a collection."""
    conn = open_library(resolve_db_path(db_path))
    catalog = LibraryCatalog(conn)

    collection = catalog.get_collection_by_id(collection_id)
    if collection is None:
        console.print(f"[red]Collection {collection_id} not found.[/red]")
        conn.close()
        raise SystemExit(1)

    old_name = collection["name"]

    try:
        catalog.rename_collection(collection_id, new_name)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        conn.close()
        raise SystemExit(1) from exc
    except Exception as exc:
        console.print(f"[red]Failed to rename collection: {exc}[/red]")
        conn.close()
        raise SystemExit(1) from exc

    console.print(f"Renamed collection [bold]{old_name}[/bold] to [bold]{new_name}[/bold].")
    conn.close()
