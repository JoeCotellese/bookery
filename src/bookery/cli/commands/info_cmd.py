# ABOUTME: The `bookery info` command for displaying detailed book metadata.
# ABOUTME: Dispatches on argument shape: cataloged ID -> DB record; path -> loose EPUB on disk.

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from bookery.cli.options import db_option, resolve_db_path
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.db.status import status_name
from bookery.formats.epub import EpubReadError, read_epub_metadata

console = Console()  # TODO: move Console() inside command for testability

# Suffixes that unambiguously identify a path argument. If the user passes one
# of these, we never try the catalog-ID path — the intent is clearly a file.
_PATH_SUFFIXES = frozenset({".epub", ".mobi", ".pdf"})


_SETTABLE_FIELDS = {
    "title",
    "subtitle",
    "authors",
    "author_sort",
    "language",
    "publisher",
    "isbn",
    "description",
    "series",
    "series_index",
    "subjects",
    "published_date",
    "original_publication_date",
    "page_count",
    "cover_url",
}


def _parse_set_pairs(pairs: tuple[str, ...]) -> dict[str, object]:
    """Parse ``field=value`` CLI pairs into a dict suitable for update_book."""
    out: dict[str, object] = {}
    for pair in pairs:
        if "=" not in pair:
            raise click.BadParameter(f"--set expects field=value, got {pair!r}")
        key, _, value = pair.partition("=")
        key = key.strip()
        if key not in _SETTABLE_FIELDS:
            raise click.BadParameter(
                f"Unknown field {key!r}. Settable fields: {', '.join(sorted(_SETTABLE_FIELDS))}"
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


def _looks_like_path(arg: str) -> bool:
    """Return True when an argument is obviously a filesystem path, not an ID.

    A bare numeric string (e.g. ``42``) is ambiguous and goes through the
    ID-first fallback; anything containing path separators, dots, leading
    ``~``, or an ebook-shaped suffix is treated as a path unconditionally.
    """
    if not arg:
        return False
    if any(ch in arg for ch in ("/", "\\")):
        return True
    if arg.startswith("~") or arg.startswith("."):
        return True
    suffix = Path(arg).suffix.lower()
    return suffix in _PATH_SUFFIXES


def _show_loose_epub(path: Path) -> None:
    """Render extracted metadata for an EPUB file that isn't in the catalog."""
    try:
        meta = read_epub_metadata(path)
    except EpubReadError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1) from exc

    table = Table(title=str(path.name), show_header=False, pad_edge=False)
    table.add_column("Field", style="bold")
    table.add_column("Value")

    table.add_row("Title", meta.title)
    table.add_row("Author", meta.author or "[dim]unknown[/dim]")
    table.add_row("Language", meta.language or "[dim]unknown[/dim]")
    table.add_row("Publisher", meta.publisher or "[dim]unknown[/dim]")
    table.add_row("ISBN", meta.isbn or "[dim]none[/dim]")
    table.add_row("Description", meta.description or "[dim]none[/dim]")
    table.add_row("Series", meta.series or "[dim]none[/dim]")
    if meta.series_index is not None:
        table.add_row("Series Index", str(meta.series_index))
    table.add_row("Cover", "yes" if meta.has_cover else "no")
    if meta.identifiers:
        ids_str = ", ".join(f"{k}={v}" for k, v in meta.identifiers.items())
        table.add_row("Identifiers", ids_str)

    console.print(table)


@click.command("info")
@click.argument("target")
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
    target: str,
    db_path: Path | None,
    show_provenance: bool,
    set_pairs: tuple[str, ...],
    lock_fields: tuple[str, ...],
    unlock_fields: tuple[str, ...],
) -> None:
    """Show metadata for a cataloged book by ID, or for a loose EPUB on disk.

    TARGET is either a book ID from the catalog or a path to an EPUB file.
    When given a numeric ID, dispatches to the catalog and supports
    ``--set field=value`` (recorded as ``user`` in the provenance table) and
    ``--lock field`` (protects a value from being clobbered by ``rematch``).

    When given a path (or any value ending in ``.epub``/``.mobi``/``.pdf``),
    reads the file directly and prints the metadata extracted from disk.
    The catalog-only flags (``--set``, ``--lock``, ``--unlock``,
    ``--provenance``) are not meaningful for loose files and are rejected.
    """
    catalog_only_flags = bool(
        set_pairs or lock_fields or unlock_fields or show_provenance,
    )

    # Unambiguous path-shaped argument: skip the catalog probe and read the
    # file directly. Combining a path with catalog-only flags is operator
    # error — we fail fast instead of silently dropping them.
    if _looks_like_path(target):
        path = Path(target).expanduser()
        if not path.exists():
            console.print(f"[red]File not found:[/red] {path}")
            raise SystemExit(1)
        if catalog_only_flags:
            raise click.UsageError(
                "--set/--lock/--unlock/--provenance only apply to cataloged "
                "books (numeric ID), not to loose files.",
            )
        _show_loose_epub(path)
        return

    # Numeric arg → try ID first, fall back to path only if a file exists.
    if target.isdigit():
        book_id = int(target)
        # TODO: wrap conn in try-finally or context manager to prevent leak on exception
        conn = open_library(resolve_db_path(db_path))
        catalog = LibraryCatalog(conn)
        record = catalog.get_by_id(book_id)
        if record is not None:
            _show_catalog_record(
                conn=conn,
                catalog=catalog,
                book_id=book_id,
                record=record,
                show_provenance=show_provenance,
                set_pairs=set_pairs,
                lock_fields=lock_fields,
                unlock_fields=unlock_fields,
            )
            return
        conn.close()
        # Catalog miss — fall back to path interpretation if the numeric
        # string happens to name a file on disk.
        fallback = Path(target)
        if fallback.exists():
            if catalog_only_flags:
                raise click.UsageError(
                    "--set/--lock/--unlock/--provenance only apply to "
                    "cataloged books (numeric ID), not to loose files.",
                )
            _show_loose_epub(fallback)
            return
        console.print(
            f"[red]Not found:[/red] no book with ID {book_id} in the catalog, "
            f"and no file at path {target!r}.",
        )
        raise SystemExit(1)

    # Non-numeric, non-path-shaped string (e.g. a UUID or bare slug).
    # The catalog only accepts integer IDs today, so this can only be a path.
    fallback = Path(target).expanduser()
    if fallback.exists():
        if catalog_only_flags:
            raise click.UsageError(
                "--set/--lock/--unlock/--provenance only apply to cataloged "
                "books (numeric ID), not to loose files.",
            )
        _show_loose_epub(fallback)
        return
    console.print(
        f"[red]Not found:[/red] {target!r} is neither a catalog ID "
        "(IDs are integers) nor a path to an existing file.",
    )
    raise SystemExit(1)


def _show_catalog_record(
    *,
    conn,  # type: ignore[no-untyped-def]
    catalog: LibraryCatalog,
    book_id: int,
    record,  # type: ignore[no-untyped-def]
    show_provenance: bool,
    set_pairs: tuple[str, ...],
    lock_fields: tuple[str, ...],
    unlock_fields: tuple[str, ...],
) -> None:
    """Render a cataloged book and apply any --set/--lock/--unlock edits."""
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
        console.print(f"[green]Unlocked:[/green] {', '.join(sorted(set(unlock_fields)))}")

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
    table.add_row("Source", str(record.source_path) if record.source_path else "—")
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
