# ABOUTME: The `bookery folder` command for opening a book's folder on disk.
# ABOUTME: Resolves an ID or title to a BookRecord and opens the folder in the OS file manager.

from pathlib import Path

import click
from rich.console import Console

from bookery.cli.options import db_option
from bookery.core.book_lookup import (
    Ambiguous,
    Found,
    NotFound,
    Suggestions,
    resolve_book,
)
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import DEFAULT_DB_PATH, open_library
from bookery.util.file_manager import (
    Headless,
    Opened,
    OpenerFailed,
    open_in_file_manager,
)

console = Console()  # TODO: move Console() inside command for testability


@click.command("folder")
@click.argument("query")
@click.option(
    "--print",
    "print_only",
    is_flag=True,
    default=False,
    help="Print the folder path instead of opening the file manager.",
)
@db_option
def folder(query: str, print_only: bool, db_path: Path | None) -> None:
    """Open the on-disk folder for a book by ID or title."""
    conn = open_library(db_path or DEFAULT_DB_PATH)
    try:
        catalog = LibraryCatalog(conn)
        result = resolve_book(catalog, query)

        if isinstance(result, NotFound):
            console.print(f"[red]Book not found:[/red] {query}")
            raise SystemExit(1)

        if isinstance(result, Ambiguous):
            console.print(
                f"[yellow]Multiple books match[/yellow] '{query}':"
            )
            for r in result.records:
                console.print(f"  [dim]{r.id}[/dim]  {r.metadata.title}")
            console.print("[dim]Re-run with a numeric ID to disambiguate.[/dim]")
            raise SystemExit(2)

        if isinstance(result, Suggestions):
            console.print(f"[red]Book not found:[/red] {query}")
            console.print("[yellow]Did you mean:[/yellow]")
            for r in result.records:
                console.print(f"  [dim]{r.id}[/dim]  {r.metadata.title}")
            raise SystemExit(1)

        assert isinstance(result, Found)
        record = result.record

        # Books that went through the match/write pipeline have an explicit
        # output_path. Books imported without --match only have source_path,
        # so fall back to the directory containing the original file.
        folder_path = record.output_path or record.source_path.parent

        if not folder_path.exists():
            console.print(
                f"[red]Folder does not exist:[/red] {folder_path}"
            )
            console.print("[dim]DB may be out of sync with the filesystem.[/dim]")
            raise SystemExit(1)

        if print_only:
            # Use click.echo (not Rich) so the path is emitted unwrapped and
            # is safe to consume from a shell pipeline.
            click.echo(str(folder_path))
            return

        open_result = open_in_file_manager(folder_path)

        if isinstance(open_result, Opened):
            return

        if isinstance(open_result, Headless):
            console.print(
                "[yellow]No graphical environment available (headless).[/yellow]"
            )
            click.echo(str(folder_path))
            return

        if isinstance(open_result, OpenerFailed):
            console.print(f"[red]Failed to open folder:[/red] {open_result.message}")
            raise SystemExit(1)
    finally:
        conn.close()
