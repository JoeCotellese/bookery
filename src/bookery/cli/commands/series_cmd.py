# ABOUTME: The `bookery series` command group for series inspection and backfill.
# ABOUTME: `ls` lists series coverage; `backfill` fills series into the catalog and EPUB files.

import logging
import os
import shutil
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from bookery.cli._match_helpers import build_metadata_provider
from bookery.cli.options import db_option, resolve_db_path, threshold_option
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.db.hashing import compute_file_hash
from bookery.db.mapping import BookRecord
from bookery.formats.epub import EpubReadError, read_calibre_series, write_epub_metadata
from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.series_heuristic import HEURISTIC_SOURCE, infer_series_from_title

logger = logging.getLogger(__name__)


def _create_provider(*, use_cache: bool = True):
    """Create the configured metadata provider, optionally cached."""
    return build_metadata_provider(use_cache=use_cache)


def _validate_selectors(book_id: int | None, backfill_all: bool, tag_name: str | None) -> None:
    """Require exactly one of BOOK_ID, --all, or --tag."""
    count = sum([book_id is not None, backfill_all, tag_name is not None])
    if count != 1:
        raise click.UsageError("Specify exactly one of: BOOK_ID, --all, or --tag.")


def _select_books(
    catalog: LibraryCatalog,
    book_id: int | None,
    backfill_all: bool,
    tag_name: str | None,
) -> list[BookRecord]:
    """Select target books; mirrors the rematch selectors."""
    if book_id is not None:
        record = catalog.get_by_id(book_id)
        return [record] if record else []
    if backfill_all:
        return catalog.list_all()
    if tag_name is not None:
        return catalog.get_books_by_tag(tag_name)
    return []


def _find_series_candidate(
    provider,
    record: BookRecord,
    threshold: float,
) -> MetadataCandidate | None:
    """Look up the book (ISBN first, then title/author) and return a usable candidate.

    Usable means: confidence at or above threshold AND carries a series name.
    """
    meta = record.metadata
    candidates: list[MetadataCandidate] = []
    if meta.isbn:
        candidates = provider.search_by_isbn(meta.isbn)
    if not candidates:
        author = meta.authors[0] if meta.authors else None
        candidates = provider.search_by_title_author(meta.title, author)

    for candidate in candidates:
        if candidate.confidence >= threshold and candidate.metadata.series:
            return candidate
    return None


def _series_fields_and_provenance(
    candidate: MetadataCandidate,
) -> tuple[dict, dict[str, str]]:
    """Extract only series/series_index plus their per-field provenance."""
    meta = candidate.metadata
    fields: dict = {"series": meta.series}
    provenance = {"series": meta.identifiers.get("provenance_series", candidate.source)}
    if meta.series_index is not None:
        fields["series_index"] = meta.series_index
        provenance["series_index"] = meta.identifiers.get(
            "provenance_series_index", candidate.source
        )
    return fields, provenance


def _stale_epub_records(records: list[BookRecord]) -> list[BookRecord]:
    """Books whose library EPUB series meta doesn't match the catalog."""
    stale: list[BookRecord] = []
    for record in records:
        if not record.metadata.series:
            continue
        out = record.output_path
        if out is None or out.suffix.lower() != ".epub" or not out.exists():
            continue
        try:
            current = read_calibre_series(out)
        except (OSError, zipfile.BadZipFile, ET.ParseError):
            continue
        if current != (record.metadata.series, record.metadata.series_index):
            stale.append(record)
    return stale


def _write_series_epub(catalog: LibraryCatalog, record: BookRecord) -> bool:
    """Rewrite one library EPUB atomically; return False if read-back verify fails.

    Same pattern as `authors fix-sort`: write to a sibling temp file, verify
    the series round-trip, then ``os.replace`` swaps it in. A failed verify
    leaves the original untouched. The new file_hash is persisted so ``verify``
    doesn't later flag the rewritten copy as changed.
    """
    src = record.output_path
    assert src is not None  # guaranteed by _stale_epub_records
    tmp = src.with_name(src.name + ".fixtmp")
    shutil.copy2(src, tmp)
    try:
        write_epub_metadata(tmp, record.metadata)
        if read_calibre_series(tmp) != (record.metadata.series, record.metadata.series_index):
            tmp.unlink(missing_ok=True)
            return False
        os.replace(tmp, src)
    except (OSError, EpubReadError):
        tmp.unlink(missing_ok=True)
        raise
    catalog.update_book(record.id, file_hash=compute_file_hash(src))
    return True


@click.group()
def series() -> None:
    """Inspect and backfill series metadata on cataloged books."""


@series.command("ls")
@db_option
def series_ls(db_path: Path | None) -> None:
    """List distinct series in the catalog with book counts and missing-position gaps."""
    console = Console()
    conn = open_library(resolve_db_path(db_path))
    try:
        rows = LibraryCatalog(conn).list_series()
    finally:
        conn.close()

    if not rows:
        console.print("[yellow]No series in the catalog yet.[/yellow]")
        return

    table = Table(title="Series")
    table.add_column("Series", style="bold")
    table.add_column("Books", justify="right")
    table.add_column("Missing #", justify="right")
    for row in rows:
        missing = str(row.missing_index_count) if row.missing_index_count else "-"
        table.add_row(row.series, str(row.book_count), missing)
    console.print(table)


@series.command("backfill")
@click.argument("book_id", type=int, required=False, default=None)
@click.option("--all", "backfill_all", is_flag=True, help="Backfill every book missing series.")
@click.option("--tag", "tag_name", type=str, help="Backfill books with this tag.")
@click.option("--dry-run", is_flag=True, help="Show what would change without writing.")
@click.option("--no-cache", is_flag=True, help="Skip the metadata response cache.")
@db_option
@threshold_option
def series_backfill(
    book_id: int | None,
    backfill_all: bool,
    tag_name: str | None,
    dry_run: bool,
    no_cache: bool,
    db_path: Path | None,
    threshold: float,
) -> None:
    """Fill missing series/series_index on cataloged books and their EPUBs.

    Looks up each book against the configured providers (ISBN first, then
    title/author) and falls back to title-pattern heuristics. Writes only
    the series fields; books that already have a series and locked fields
    are left untouched. Library EPUBs whose calibre:series meta doesn't
    match the catalog are rewritten so Kobo (firmware 4.20+) groups them
    on the next sync.
    """
    console = Console()
    _validate_selectors(book_id, backfill_all, tag_name)

    conn = open_library(resolve_db_path(db_path))
    try:
        catalog = LibraryCatalog(conn)
        try:
            books = _select_books(catalog, book_id, backfill_all, tag_name)
        except ValueError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            return

        if not books:
            if book_id is not None:
                console.print(f"[red]Error:[/red] Book with id {book_id} not found.")
            else:
                console.print("[yellow]No books to backfill.[/yellow]")
            return

        targets = [b for b in books if not b.metadata.series]
        skipped_existing = len(books) - len(targets)
        if skipped_existing:
            console.print(
                f"[dim]Skipping {skipped_existing} book"
                f"{'s' if skipped_existing != 1 else ''} that already have a series.[/dim]"
            )
        filled = 0
        missed = 0
        if not targets:
            console.print("[green]No catalog rows need backfilling.[/green]")
        provider = _create_provider(use_cache=not no_cache) if targets else None

        for record in targets:
            assert provider is not None  # targets non-empty ⇒ provider was created
            title = record.metadata.title
            fields: dict
            candidate = _find_series_candidate(provider, record, threshold)
            if candidate is not None:
                fields, provenance = _series_fields_and_provenance(candidate)
                source = provenance["series"]
            else:
                guess = infer_series_from_title(title or "")
                if guess is None:
                    console.print(f"  [dim]{record.id} {title}: no series found[/dim]")
                    missed += 1
                    continue
                fields = {"series": guess.series}
                if guess.series_index is not None:
                    fields["series_index"] = guess.series_index
                provenance = dict.fromkeys(fields, HEURISTIC_SOURCE)
                source = HEURISTIC_SOURCE

            index_note = f" #{fields['series_index']:g}" if "series_index" in fields else ""
            if dry_run:
                console.print(
                    f"  [cyan]{record.id}[/cyan] {title} → "
                    f"{fields['series']}{index_note} [dim]({source}, dry-run)[/dim]"
                )
                filled += 1
                continue

            written = catalog.update_book(
                record.id,
                source=source,
                provenance=provenance,
                respect_locked=True,
                **fields,
            )
            locked = set(fields) - set(written)
            if locked:
                console.print(
                    f"  [dim]{record.id} {title}: preserved locked field(s): "
                    f"{', '.join(sorted(locked))}[/dim]"
                )
            if written:
                console.print(
                    f"  [green]{record.id}[/green] {title} → "
                    f"{fields['series']}{index_note} [dim]({source})[/dim]"
                )
                filled += 1
            else:
                missed += 1

        # Push series into the library EPUB files so Kobo can group them (#298).
        # Re-select so books filled above are seen with their new series; in a
        # dry run the catalog is untouched, so this covers already-set books.
        stale = _stale_epub_records(_select_books(catalog, book_id, backfill_all, tag_name))
        if stale and dry_run:
            console.print(
                f"[dim]dry-run:[/dim] {len(stale)} EPUB file(s) would be rewritten "
                "with series metadata."
            )
        elif stale:
            rewritten = 0
            failed_writes = 0
            for record in stale:
                try:
                    ok = _write_series_epub(catalog, record)
                except (OSError, EpubReadError) as exc:
                    console.print(
                        f"  [red]{record.id} {record.metadata.title}: "
                        f"EPUB write failed: {exc}[/red]"
                    )
                    failed_writes += 1
                    continue
                if ok:
                    rewritten += 1
                else:
                    failed_writes += 1
                    console.print(
                        f"  [red]{record.id} {record.metadata.title}: "
                        "verify failed; original kept[/red]"
                    )
            msg = f"Updated series metadata in [green]{rewritten}[/green] EPUB file(s)."
            if failed_writes:
                msg += f" [red]{failed_writes} failed.[/red]"
            console.print(msg)
    finally:
        conn.close()

    label = "would fill" if dry_run else "filled"
    console.print(f"\nDone: [green]{filled} {label}[/green], [yellow]{missed} unresolved[/yellow]")
