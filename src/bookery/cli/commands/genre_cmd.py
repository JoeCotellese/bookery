# ABOUTME: The `bookery genre` command group for managing book genres.
# ABOUTME: Provides ls, assign, and unmatched subcommands for genre operations.

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from bookery.cli.options import db_option
from bookery.core.genre_applier import apply_genres
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import DEFAULT_DB_PATH, open_library

console = Console()


@click.group("genre")
def genre() -> None:
    """Manage book genres."""


@genre.command("ls")
@db_option
def genre_ls(db_path: Path | None) -> None:
    """List all canonical genres with book counts."""
    conn = open_library(db_path or DEFAULT_DB_PATH)
    catalog = LibraryCatalog(conn)

    genres = catalog.list_genres()

    table = Table()
    table.add_column("Genre", style="cyan")
    table.add_column("Books", style="dim", justify="right")

    for name, count in genres:
        table.add_row(name, str(count))

    console.print(table)
    conn.close()


@genre.command("assign")
@click.argument("book_id", type=int)
@click.argument("genre_name")
@click.option("--primary", is_flag=True, help="Set as the primary genre.")
@db_option
def genre_assign(book_id: int, genre_name: str, primary: bool, db_path: Path | None) -> None:
    """Assign a genre to a book."""
    conn = open_library(db_path or DEFAULT_DB_PATH)
    catalog = LibraryCatalog(conn)

    try:
        catalog.add_genre(book_id, genre_name, is_primary=primary)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        conn.close()
        raise SystemExit(1) from exc

    record = catalog.get_by_id(book_id)
    title = record.metadata.title if record else f"Book {book_id}"
    console.print(
        f"Assigned [cyan]{genre_name}[/cyan] to [bold]{title}[/bold]."
    )
    conn.close()


@genre.command("unmatched")
@db_option
def genre_unmatched(db_path: Path | None) -> None:
    """Show books with subjects but no genre assigned."""
    conn = open_library(db_path or DEFAULT_DB_PATH)
    catalog = LibraryCatalog(conn)

    unmatched = catalog.get_unmatched_subjects()

    if not unmatched:
        console.print("[green]No books need genre assignment.[/green]")
        conn.close()
        return

    table = Table()
    table.add_column("ID", style="dim", width=4)
    table.add_column("Title", style="bold")
    table.add_column("Subjects")

    for book_id, title, subjects in unmatched:
        table.add_row(str(book_id), title, ", ".join(subjects))

    console.print(table)
    console.print(f"\n[dim]{len(unmatched)} book(s) need genre assignment[/dim]")
    conn.close()


@genre.command("apply")
@click.option("--dry-run", is_flag=True, help="Show what would be assigned without writing.")
@click.option("--force", is_flag=True, help="Re-evaluate all books, even those with genres.")
@db_option
@click.pass_context
def genre_apply(ctx: click.Context, dry_run: bool, force: bool, db_path: Path | None) -> None:
    """Batch-assign genres from subjects for cataloged books."""
    conn = open_library(db_path or DEFAULT_DB_PATH)
    catalog = LibraryCatalog(conn)
    verbose = ctx.parent.params.get("verbose", 0) if ctx.parent else 0

    result = apply_genres(catalog, dry_run=dry_run, force=force)

    if dry_run:
        console.print("[bold yellow]Dry run[/bold yellow] — no changes written.\n")

    if result.assigned:
        if verbose or dry_run:
            for book_id, title, primary_genre in result.assigned:
                console.print(
                    f"  [bold]{title}[/bold] → [cyan]{primary_genre}[/cyan]"
                )
            console.print()

    console.print(f"[green]{len(result.assigned)}[/green] book(s) assigned genres.")

    if result.unmatched:
        console.print(
            f"[yellow]{len(result.unmatched)}[/yellow] book(s) unmatched "
            f"— run [dim]bookery genre unmatched[/dim] for details."
        )

    conn.close()
