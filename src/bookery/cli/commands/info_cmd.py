# ABOUTME: The `bookery info` command for displaying detailed book metadata.
# ABOUTME: Shows all fields for a single cataloged book by ID.

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from bookery.cli.options import db_option, resolve_db_path
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.db.status import status_name

console = Console()  # TODO: move Console() inside command for testability


_SETTABLE_FIELDS = {
    "title", "subtitle", "authors", "author_sort", "language", "publisher", "isbn",
    "description", "series", "series_index", "subjects", "published_date",
    "original_publication_date", "page_count", "cover_url",
}


def _parse_set_pairs(pairs: tuple[str, ...]) -> dict[str, object]:
    """Parse ``field=value`` CLI pairs into a dict suitable for update_book."""
    out: dict[str, object] = {}
    for pair in pairs:
        if "=" not in pair:
            raise click.BadParameter(
                f"--set expects field=value, got {pair!r}"
            )
        key, _, value = pair.partition("=")
        key = key.strip()
        if key not in _SETTABLE_FIELDS:
            raise click.BadParameter(
                f"Unknown field {key!r}. Settable fields: "
                f"{', '.join(sorted(_SETTABLE_FIELDS))}"
            )
        if key in ("authors", "subjects"):
            out[key] = [a.strip() for a in value.split(",") if a.strip()]
        elif key == "page_count":
            out[key] = int(value)
        elif key == "series_index":
            out[key] = float(value)
        else:
            out[key] = value
    return out


@click.command("info")
@click.argument("book_id", type=int)
@db_option
@click.option(
    "--provenance",
    "show_provenance",
    is_flag=True,
    help="Show the per-field source and fetched_at timestamps.",
)
@click.option(
    "--set",
    "set_pairs",
    multiple=True,
    metavar="FIELD=VALUE",
    help="Set a field value and record provenance as 'user'. Repeatable.",
)
@click.option(
    "--lock",
    "lock_fields",
    multiple=True,
    metavar="FIELD",
    help="Lock a field against automatic rematch overwrites. Repeatable.",
)
@click.option(
    "--unlock",
    "unlock_fields",
    multiple=True,
    metavar="FIELD",
    help="Unlock a previously locked field. Repeatable.",
)
def info(
    book_id: int,
    db_path: Path | None,
    show_provenance: bool,
    set_pairs: tuple[str, ...],
    lock_fields: tuple[str, ...],
    unlock_fields: tuple[str, ...],
) -> None:
    """Show detailed metadata for a book by ID.

    Use ``--set field=value`` to hand-edit values (recorded as ``user`` in
    the provenance table). Add ``--lock field`` to protect a value from
    being clobbered by a future ``rematch``.
    """
    # TODO: wrap conn in try-finally or context manager to prevent leak on exception
    conn = open_library(resolve_db_path(db_path))
    catalog = LibraryCatalog(conn)

    record = catalog.get_by_id(book_id)

    if record is None:
        console.print(f"[red]Book {book_id} not found.[/red]")
        conn.close()
        raise SystemExit(1)

    if set_pairs:
        parsed = _parse_set_pairs(set_pairs)
        catalog.update_book(book_id, source="user", **parsed)  # type: ignore[arg-type]
        record = catalog.get_by_id(book_id)
        assert record is not None
        console.print(f"[green]Updated:[/green] {', '.join(sorted(parsed))}")

    for field_name in lock_fields:
        catalog.set_field_lock(book_id, field_name, True)
    for field_name in unlock_fields:
        catalog.set_field_lock(book_id, field_name, False)
    if lock_fields:
        console.print(f"[green]Locked:[/green] {', '.join(sorted(set(lock_fields)))}")
    if unlock_fields:
        console.print(
            f"[green]Unlocked:[/green] {', '.join(sorted(set(unlock_fields)))}"
        )

    if show_provenance:
        prov = catalog.get_provenance(book_id)
        if not prov:
            console.print("[yellow]No provenance recorded for this book.[/yellow]")
            conn.close()
            return
        table = Table(title=f"Provenance for book {book_id}")
        table.add_column("Field", style="bold")
        table.add_column("Source")
        table.add_column("Fetched")
        table.add_column("Confidence", justify="right")
        table.add_column("Locked")
        for entry in prov.values():
            conf = f"{entry.confidence:.0%}" if entry.confidence is not None else "—"
            table.add_row(
                entry.field_name,
                entry.source,
                entry.fetched_at,
                conf,
                "yes" if entry.locked else "no",
            )
        console.print(table)
        conn.close()
        return

    meta = record.metadata
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("Field", style="bold", width=14)
    table.add_column("Value")

    table.add_row("ID", str(record.id))
    table.add_row("Title", meta.title)
    if meta.subtitle:
        table.add_row("Subtitle", meta.subtitle)
    table.add_row("Author", meta.author or "unknown")
    if meta.author_sort:
        table.add_row("Author Sort", meta.author_sort)
    table.add_row("Language", meta.language or "?")
    if meta.publisher:
        table.add_row("Publisher", meta.publisher)
    if meta.isbn:
        table.add_row("ISBN", meta.isbn)
    if meta.published_date:
        table.add_row("Published", meta.published_date)
    if meta.original_publication_date:
        table.add_row("First Published", meta.original_publication_date)
    if meta.page_count is not None:
        table.add_row("Pages", str(meta.page_count))
    if meta.rating is not None:
        count = meta.ratings_count
        count_str = f" ({count:,} ratings)" if count else ""
        table.add_row("Rating", f"⭐ {meta.rating:.1f}{count_str}")
    if meta.cover_url:
        table.add_row("Cover URL", meta.cover_url)
    if meta.description:
        table.add_row("Description", meta.description)
    if meta.series:
        idx = meta.series_index
        series_str = f"{meta.series} #{idx:g}" if idx is not None else meta.series
        table.add_row("Series", series_str)
    genres = catalog.get_genres_for_book(book_id)
    if genres:
        genre_strs = []
        for name, is_primary in genres:
            genre_strs.append(f"{name} *" if is_primary else name)
        table.add_row("Genre", ", ".join(genre_strs))
    tags = catalog.get_tags_for_book(book_id)
    if tags:
        table.add_row("Tags", ", ".join(tags))
    table.add_row("Source", str(record.source_path))
    if record.output_path:
        table.add_row("Output", str(record.output_path))
    if record.metadata_matched_at:
        table.add_row("Matched", record.metadata_matched_at)
    table.add_row("Hash", record.file_hash)
    table.add_row("Added", record.date_added)
    table.add_row("Modified", record.date_modified)

    console.print(table)

    book_status = catalog.get_book_status(book_id)
    device_state = catalog.get_device_read_state_for_book(book_id)
    if book_status is not None or device_state is not None:
        reading = Table(show_header=False, box=None, pad_edge=False)
        reading.add_column("Field", style="bold", width=14)
        reading.add_column("Value")
        if book_status is not None:
            reading.add_row("Status", status_name(book_status.status))
        elif device_state is not None:
            # No user mark yet — surface the device's view rather than render
            # an empty section just because device_read_state exists.
            reading.add_row("Status", status_name(device_state.read_status))
        if device_state is not None and device_state.percent_read is not None:
            reading.add_row("Progress", f"{device_state.percent_read:.0%}")
        if device_state is not None and device_state.last_read_at:
            reading.add_row("Last opened", device_state.last_read_at)
        if device_state is not None:
            label = (
                f"{device_state.device_kind.title()} ({device_state.device_label})"
                if device_state.device_label
                else device_state.device_kind.title()
            )
            reading.add_row("Device", label)
        console.print()
        console.print("[bold]Reading[/bold]")
        console.print(reading)

    conn.close()
