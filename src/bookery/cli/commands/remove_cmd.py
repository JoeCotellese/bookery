# ABOUTME: The `bookery remove` command for deleting books from catalog and disk.
# ABOUTME: Prompts per ID by default, supports -y/--yes, --keep-file, and multi-ID input.

from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from bookery.cli.options import db_option, resolve_db_path
from bookery.core.remove import RemoveResult, remove_book
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library

console = Console()


def _human_size(num_bytes: int) -> str:
    """Render a byte count as KB/MB/GB to one decimal place."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024.0
    return f"{size:.1f} PB"


def _build_confirmation_panel(
    catalog: LibraryCatalog,
    book_id: int,
    *,
    keep_file: bool,
) -> Panel | None:
    """Build a Rich panel summarizing what removing this book will touch.

    Returns None if the book ID isn't in the catalog — the caller treats
    that as an error case and reports it separately.
    """
    record = catalog.get_by_id(book_id)
    if record is None:
        return None

    output_path = record.output_path
    size_text = "n/a"
    if output_path is not None:
        try:
            size_text = _human_size(output_path.stat().st_size)
        except OSError:
            size_text = "missing"

    tag_count = len(catalog.get_tags_for_book(book_id))
    genre_count = len(catalog.get_genres_for_book(book_id))

    # Duplicate cluster check (same query the core uses, surfaced for UX)
    dup_count = 0
    if output_path is not None:
        cursor = catalog._conn.execute(
            "SELECT COUNT(*) FROM books WHERE output_path = ? AND id != ?",
            (str(output_path), book_id),
        )
        dup_count = int(cursor.fetchone()[0])

    body = Text()
    body.append(f"ID:      {book_id}\n", style="bold")
    body.append(f"Title:   {record.metadata.title}\n")
    body.append(f"Author:  {record.metadata.author or 'Unknown'}\n")
    body.append(f"Path:    {output_path if output_path else '(no file)'}\n")
    body.append(f"Size:    {size_text}\n")
    body.append(f"Tags:    {tag_count}    Genres: {genre_count}\n")
    if dup_count > 0:
        body.append(
            f"Note: {dup_count} other catalog entries point at this same "
            "file; the file will be kept on disk.\n",
            style="yellow",
        )
    if keep_file:
        body.append("Mode: --keep-file (file on disk will be preserved)\n", style="cyan")

    return Panel(body, title="Remove this book?", border_style="red")


def _render_result(result: RemoveResult) -> None:
    """Print the per-book outcome line plus any warnings."""
    console.print(
        f'[green]Removed[/green] "{result.title}" by {result.author} (ID {result.book_id})'
    )
    if result.file_removed:
        console.print(f"  [dim]file:[/dim] {result.file_path}")
    for sibling in result.siblings_removed:
        console.print(f"  [dim]sibling:[/dim] {sibling}")
    for warning in result.warnings:
        console.print(f"  [yellow]warning:[/yellow] {warning}")


@click.command("remove")
@click.argument("book_ids", nargs=-1, type=int, required=True)
@db_option
@click.option(
    "-y",
    "--yes",
    "auto_accept",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt (scripting-friendly).",
)
@click.option(
    "--keep-file",
    "keep_file",
    is_flag=True,
    default=False,
    help="Delete only the catalog row; leave the file on disk untouched.",
)
def remove(
    book_ids: tuple[int, ...],
    db_path: Path | None,
    auto_accept: bool,
    keep_file: bool,
) -> None:
    """Remove one or more books from the catalog.

    By default the on-disk file (and any sibling files sharing its stem,
    e.g. ``.kepub.epub``) is deleted along with the catalog row. Use
    ``--keep-file`` to leave the file in place — handy when you're about
    to re-import with corrected metadata.

    Symlinks: if a book's ``output_path`` is a symlink, only the link is
    removed; the target file is preserved.

    Exit codes:
      0  All requested IDs handled (removed or declined)
      1  At least one ID could not be removed
      2  Usage error (no IDs supplied)
    """
    conn = open_library(resolve_db_path(db_path))
    catalog = LibraryCatalog(conn)

    failures = 0
    try:
        for book_id in book_ids:
            panel = _build_confirmation_panel(catalog, book_id, keep_file=keep_file)
            if panel is None:
                console.print(f"[red]error:[/red] book {book_id} not found")
                failures += 1
                continue

            console.print(panel)

            if not auto_accept:
                prompt = (
                    "Delete catalog entry (keep file on disk)?"
                    if keep_file
                    else "Delete this book?"
                )
                if not click.confirm(prompt, default=False):
                    console.print(f"[dim]Skipped {book_id}[/dim]")
                    continue

            try:
                result = remove_book(catalog, book_id, keep_file=keep_file)
            except ValueError as exc:
                console.print(f"[red]error:[/red] {exc}")
                failures += 1
                continue
            except OSError as exc:
                console.print(f"[red]error:[/red] {exc}")
                failures += 1
                continue

            _render_result(result)
    finally:
        conn.close()

    if failures:
        raise click.exceptions.Exit(1)
