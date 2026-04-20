# ABOUTME: The `bookery genre` command group for managing book genres.
# ABOUTME: Provides ls, assign, and unmatched subcommands for genre operations.

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from bookery.cli.options import db_option, resolve_db_path
from bookery.core.genre_applier import (
    apply_genres,
    collect_unmatched_subject_frequencies,
)
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library

console = Console()


@click.group("genre")
def genre() -> None:
    """Manage book genres."""


@genre.command("ls")
@db_option
def genre_ls(db_path: Path | None) -> None:
    """List all canonical genres with book counts."""
    conn = open_library(resolve_db_path(db_path))
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
    conn = open_library(resolve_db_path(db_path))
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
    conn = open_library(resolve_db_path(db_path))
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


@genre.command("stats")
@click.option("--limit", type=int, default=25, show_default=True)
@db_option
def genre_stats(limit: int, db_path: Path | None) -> None:
    """Show the most common subjects that don't map to a canonical genre."""
    conn = open_library(resolve_db_path(db_path))
    catalog = LibraryCatalog(conn)

    freq = collect_unmatched_subject_frequencies(catalog)
    if not freq:
        console.print("[green]No unmatched subjects — every subject maps cleanly.[/green]")
        conn.close()
        return

    table = Table(title="Unmatched subjects")
    table.add_column("Subject")
    table.add_column("Count", justify="right", style="dim")

    for subject, count in freq[:limit]:
        table.add_row(subject, str(count))
    console.print(table)
    if len(freq) > limit:
        console.print(f"[dim]… {len(freq) - limit} more[/dim]")
    conn.close()


@genre.command("apply")
@click.option("--dry-run", is_flag=True, help="Show what would be assigned without writing.")
@click.option("--force", is_flag=True, help="Re-evaluate all books, even those with genres.")
@db_option
@click.pass_context
def genre_apply(ctx: click.Context, dry_run: bool, force: bool, db_path: Path | None) -> None:
    """Batch-assign genres from subjects for cataloged books."""
    conn = open_library(resolve_db_path(db_path))
    catalog = LibraryCatalog(conn)
    verbose = ctx.parent.params.get("verbose", 0) if ctx.parent else 0

    result = apply_genres(catalog, dry_run=dry_run, force=force)

    if dry_run:
        console.print("[bold yellow]Dry run[/bold yellow] — no changes written.\n")

    if result.assigned and (verbose or dry_run):
        for _book_id, title, primary_genre in result.assigned:
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


@genre.command("auto")
@click.option("--all", "all_books", is_flag=True, help="Re-evaluate every book.")
@click.option("--dry-run", is_flag=True, help="Show what would be assigned without writing.")
@db_option
@click.pass_context
def genre_auto(
    ctx: click.Context,
    all_books: bool,
    dry_run: bool,
    db_path: Path | None,
) -> None:
    """Auto-map subjects to canonical genres across the catalog.

    Without ``--all``, only books that don't yet have a genre are processed
    (matches ``genre apply``). With ``--all``, every book is re-evaluated.
    """
    ctx.invoke(genre_apply, dry_run=dry_run, force=all_books, db_path=db_path)
