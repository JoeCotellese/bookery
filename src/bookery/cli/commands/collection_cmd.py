# ABOUTME: The `bookery collections` command group for managing book collections.
# ABOUTME: Static (create/add-books/remove-books) and rule-based (--query/edit/preview) curation.

from pathlib import Path
from typing import cast

import click
from rich.console import Console
from rich.table import Table

from bookery.cli.options import db_option, resolve_db_path
from bookery.collections import CollectionQueryError, parse_collection_query
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library

console = Console()


@click.group("collections")
def collections() -> None:
    """Manage book collections (static curation or rule-based queries)."""


@collections.command("create")
@click.argument("name")
@click.option("--description", "-d", help="Optional description for the collection.")
@click.option(
    "--query",
    "-q",
    "query",
    default=None,
    help="Rule for a rule-based collection, e.g. 'genre:\"Science Fiction\"' or series:Dune.",
)
@db_option
def collections_create(
    name: str, description: str | None, query: str | None, db_path: Path | None
) -> None:
    """Create a new collection.

    Pass --query to create a rule-based collection whose membership is derived
    live from the rule (e.g. --query 'genre:"Science Fiction"'); omit it for a
    static, hand-curated collection.
    """
    # Validate the rule before touching the database so a bad query never
    # creates an empty collection.
    if query is not None:
        try:
            parse_collection_query(query)
        except CollectionQueryError as exc:
            console.print(f"[red]{exc}[/red]")
            raise SystemExit(1) from exc

    conn = open_library(resolve_db_path(db_path))
    catalog = LibraryCatalog(conn)

    try:
        collection_id = catalog.create_collection(name, description, query)
    except Exception as exc:
        console.print(f"[red]Failed to create collection: {exc}[/red]")
        conn.close()
        raise SystemExit(1) from exc

    if query:
        console.print(f"Created rule-based collection [bold]{name}[/bold] (ID: {collection_id}).")
    else:
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
@click.option(
    "--sync-status",
    "show_sync_status",
    is_flag=True,
    help="Show shelf sync status per device.",
)
@db_option
def collections_show(collection_id: int, show_sync_status: bool, db_path: Path | None) -> None:
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
    if collection.get("query"):
        console.print(f"[dim]Query:[/dim] {collection['query']} [dim](rule-based)[/dim]")
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

    # Show sync status if requested
    if show_sync_status:
        console.print()
        _show_collection_sync_status(conn, catalog, collection_id)

    conn.close()


def _show_collection_sync_status(conn, catalog: LibraryCatalog, collection_id: int) -> None:
    """Display shelf sync status for a collection across devices."""
    # Get all devices
    devices = catalog.list_devices()
    if not devices:
        console.print("[dim]No devices configured.[/dim]")
        return

    table = Table(title="Shelf Sync Status")
    table.add_column("Device", style="cyan")
    table.add_column("Serial")
    table.add_column("Last Pushed", style="dim")
    table.add_column("Books on Device")
    table.add_column("Status", style="green")

    for device in devices:
        device_id = cast(int, device["id"])
        shelf_state = catalog.get_collection_shelf_state(device_id, collection_id)

        if shelf_state:
            table.add_row(
                str(device["label"] or device["kind"]),
                str(device["serial"]),
                str(shelf_state["last_pushed_at"]),
                str(shelf_state["book_count_on_device"] or "0"),
                "[green]Synced[/green]",
            )
        else:
            table.add_row(
                str(device["label"] or device["kind"]),
                str(device["serial"]),
                "Never",
                "—",
                "[dim]Not synced[/dim]",
            )

    console.print(table)


@collections.command("edit")
@click.argument("collection_id", type=int)
@click.option(
    "--query",
    "query",
    default=None,
    help="Convert to a rule-based collection with this rule.",
)
@click.option(
    "--clear-query",
    "clear_query",
    is_flag=True,
    help="Convert a rule-based collection to static, snapshotting current members.",
)
@db_option
def collections_edit(
    collection_id: int, query: str | None, clear_query: bool, db_path: Path | None
) -> None:
    """Change a collection's rule (convert static <-> rule-based).

    Pass exactly one of --query (static -> rule-based) or --clear-query
    (rule-based -> static, snapshotting the current members).
    """
    if query is not None and clear_query:
        console.print("[red]Use either --query or --clear-query, not both.[/red]")
        raise SystemExit(1)
    if query is None and not clear_query:
        console.print("[red]Specify --query '<rule>' or --clear-query.[/red]")
        raise SystemExit(1)

    if query is not None:
        try:
            parse_collection_query(query)
        except CollectionQueryError as exc:
            console.print(f"[red]{exc}[/red]")
            raise SystemExit(1) from exc

    conn = open_library(resolve_db_path(db_path))
    catalog = LibraryCatalog(conn)

    collection = catalog.get_collection_by_id(collection_id)
    if collection is None:
        console.print(f"[red]Collection {collection_id} not found.[/red]")
        conn.close()
        raise SystemExit(1)

    if clear_query:
        if collection.get("query") is None:
            console.print(f"[red]Collection {collection_id} is already static.[/red]")
            conn.close()
            raise SystemExit(1)
        catalog.clear_collection_query(collection_id)
        console.print(
            f"Converted [bold]{collection['name']}[/bold] to a static collection "
            "(members snapshotted)."
        )
    else:
        catalog.set_collection_query(collection_id, query)  # type: ignore[arg-type]
        console.print(f"Set rule for [bold]{collection['name']}[/bold]: {query}")

    conn.close()


@collections.command("preview")
@click.option(
    "--query",
    "query",
    required=True,
    help="Rule to preview, e.g. 'genre:\"Science Fiction\"' or series:Dune.",
)
@db_option
def collections_preview(query: str, db_path: Path | None) -> None:
    """Preview which books a rule matches, without saving a collection."""
    conn = open_library(resolve_db_path(db_path))
    catalog = LibraryCatalog(conn)

    try:
        books = catalog.preview_query(query)
    except CollectionQueryError as exc:
        console.print(f"[red]{exc}[/red]")
        conn.close()
        raise SystemExit(1) from exc

    console.print(f"[bold]{len(books)} book(s) match[/bold] [cyan]{query}[/cyan]:")
    if not books:
        conn.close()
        return

    table = Table()
    table.add_column("ID", style="dim", width=6)
    table.add_column("Title", style="bold")
    table.add_column("Author(s)")

    for book in books:
        authors = ", ".join(book.metadata.authors) if book.metadata.authors else "Unknown"
        table.add_row(str(book.id), book.metadata.title, authors)

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
