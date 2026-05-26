# ABOUTME: The `bookery read`, `bookery unread`, `bookery reading` commands.
# ABOUTME: Set catalog-side book_status; --bulk-from FILE applies to many books at once.

from datetime import UTC, datetime
from pathlib import Path

import click
from rich.console import Console

from bookery.cli.options import db_option, resolve_db_path
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.db.status import (
    STATUS_FINISHED,
    STATUS_READING,
    STATUS_UNREAD,
    status_name,
)

console = Console()


def parse_bulk_ids(text: str) -> list[int]:
    """Parse a `--bulk-from` file body into a list of positive integers.

    Format: one ID per line. Blank lines are skipped. Lines whose first
    non-whitespace character is `#` are treated as comments and skipped.
    Each surviving line must parse as a positive (>= 1) integer; anything
    else raises ValueError naming the line number and content so the user
    can fix the file rather than guess.
    """
    ids: list[int] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            value = int(stripped)
        except ValueError as exc:
            raise ValueError(f"Line {lineno}: not an integer: {stripped!r}") from exc
        if value <= 0:
            raise ValueError(f"Line {lineno}: book ID must be positive, got {value}")
        ids.append(value)
    return ids


def _now_iso() -> str:
    """UTC ISO timestamp with seconds precision — matches the P1a pull path."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def _resolve_book_ids(*, book_id: int | None, bulk_from: Path | None) -> list[int]:
    """Return the list of book IDs to operate on, validating mutual exclusion.

    Exactly one of (positional ``book_id``, ``--bulk-from FILE``) must be
    supplied. Both-or-neither is a usage error surfaced as a Click
    BadParameter so Click formats the help-style message instead of a
    bare traceback.
    """
    if book_id is None and bulk_from is None:
        raise click.UsageError("Provide a BOOK_ID argument or --bulk-from FILE.")
    if book_id is not None and bulk_from is not None:
        raise click.UsageError("BOOK_ID and --bulk-from are mutually exclusive.")
    if bulk_from is not None:
        text = Path(bulk_from).read_text()
        try:
            ids = parse_bulk_ids(text)
        except ValueError as exc:
            raise click.BadParameter(str(exc), param_hint="--bulk-from") from exc
        if not ids:
            raise click.UsageError(f"No book IDs found in {bulk_from}.")
        return ids
    assert book_id is not None
    return [book_id]


def _apply_status(
    *,
    db_path: Path | None,
    book_id: int | None,
    bulk_from: Path | None,
    status: int,
) -> None:
    """Shared implementation for the read/unread/reading commands.

    Single-ID mode exits non-zero if the book doesn't exist (so a typo at the
    CLI fails loudly). Bulk mode is forgiving: it warns and skips unknown IDs,
    then reports a count at the end — the common bulk case is "I just imported
    my Calibre library and pasted in 200 IDs", and one stale row shouldn't
    abort the whole operation.
    """
    ids = _resolve_book_ids(book_id=book_id, bulk_from=bulk_from)
    is_bulk = bulk_from is not None
    name = status_name(status).lower()

    conn = open_library(resolve_db_path(db_path))
    try:
        catalog = LibraryCatalog(conn)
        now = _now_iso()
        applied = 0
        for bid in ids:
            try:
                catalog.set_book_status(book_id=bid, status=status, updated_at=now)
            except ValueError as exc:
                if is_bulk:
                    console.print(f"[yellow]Skipped {bid}: {exc}[/yellow]")
                    continue
                console.print(f"[red]{exc}[/red]")
                raise SystemExit(1) from exc
            applied += 1
            if not is_bulk:
                record = catalog.get_by_id(bid)
                title = record.metadata.title if record else f"book {bid}"
                console.print(f"[green]Marked[/green] [bold]{title}[/bold] as {name}.")
        if is_bulk:
            console.print(f"[green]Marked {applied} book(s) as {name}.[/green]")
    finally:
        conn.close()


_bulk_from_option = click.option(
    "--bulk-from",
    "bulk_from",
    type=click.Path(path_type=Path, exists=True, dir_okay=False, readable=True),
    default=None,
    help="Read one book ID per line from FILE. Blank lines and #-comments are skipped.",
)


@click.command("read")
@click.argument("book_id", type=int, required=False)
@_bulk_from_option
@db_option
def read_cmd(book_id: int | None, bulk_from: Path | None, db_path: Path | None) -> None:
    """Mark a book as finished (status = 2)."""
    _apply_status(db_path=db_path, book_id=book_id, bulk_from=bulk_from, status=STATUS_FINISHED)


@click.command("unread")
@click.argument("book_id", type=int, required=False)
@_bulk_from_option
@db_option
def unread_cmd(book_id: int | None, bulk_from: Path | None, db_path: Path | None) -> None:
    """Mark a book as unread (status = 0)."""
    _apply_status(db_path=db_path, book_id=book_id, bulk_from=bulk_from, status=STATUS_UNREAD)


@click.command("reading")
@click.argument("book_id", type=int, required=False)
@_bulk_from_option
@db_option
def reading_cmd(book_id: int | None, bulk_from: Path | None, db_path: Path | None) -> None:
    """Mark a book as in-progress (status = 1)."""
    _apply_status(db_path=db_path, book_id=book_id, bulk_from=bulk_from, status=STATUS_READING)
