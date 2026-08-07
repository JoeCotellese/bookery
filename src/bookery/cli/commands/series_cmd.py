# ABOUTME: The `bookery series` command group for series inspection and backfill.
# ABOUTME: `ls` lists series coverage; `backfill` fills series into the catalog and EPUB files.

import logging
import os
import shutil
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from bookery.cli._match_helpers import build_metadata_provider
from bookery.cli.options import db_option, resolve_db_path, threshold_option
from bookery.core.pipeline import _verify_write
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.db.hashing import compute_file_hash
from bookery.db.mapping import BookRecord
from bookery.formats.epub import EpubReadError, read_calibre_series, write_epub_metadata
from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.series_heuristic import HEURISTIC_SOURCE, infer_series_from_title
from bookery.metadata.title_correspondence import leading_book_number, titles_correspond

logger = logging.getLogger(__name__)

# ``ZipFile.read`` raises KeyError for a member that isn't in the archive, so a
# file that is a valid zip but has no META-INF/container.xml — or whose
# container names an OPF that isn't there — surfaces as KeyError, not OSError.
_EPUB_SCAN_ERRORS = (OSError, zipfile.BadZipFile, ET.ParseError, KeyError)
_EPUB_WRITE_ERRORS = (*_EPUB_SCAN_ERRORS, EpubReadError)


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


@dataclass(frozen=True)
class _SeriesLookup:
    """Outcome of looking for a candidate whose series we're willing to trust.

    ``identity_confirmed`` records that the candidate came back from an ISBN
    lookup, which settles identity outright. Title/author matches only earn
    trust by clearing the correspondence check, and that distinction decides
    whether the candidate's series position is trustworthy too.
    """

    candidate: MetadataCandidate | None
    identity_confirmed: bool = False
    rejection: str | None = None


def _find_series_candidate(
    provider,
    record: BookRecord,
    threshold: float,
) -> _SeriesLookup:
    """Look up the book (ISBN first, then title/author) and return a usable candidate.

    Usable means: confidence at or above threshold, carries a series name, and
    — on the title/author path — has a title that actually corresponds to the
    book we're backfilling. A confidence score is computed for the match as a
    whole and says nothing about the series field specifically: a title with
    little matchable signal ("Book 17 - Remnant") can return a
    threshold-clearing candidate for a different book entirely, whose series
    and position then get written verbatim (#303).
    """
    meta = record.metadata
    candidates: list[MetadataCandidate] = []
    by_isbn = False
    if meta.isbn:
        candidates = provider.search_by_isbn(meta.isbn)
        by_isbn = bool(candidates)
    if not candidates:
        author = meta.authors[0] if meta.authors else None
        candidates = provider.search_by_title_author(meta.title, author)

    rejection: str | None = None
    for candidate in candidates:
        if candidate.confidence < threshold or not candidate.metadata.series:
            continue
        if by_isbn:
            return _SeriesLookup(candidate=candidate, identity_confirmed=True)
        verdict = titles_correspond(meta.title or "", candidate.metadata.title or "")
        if verdict.corresponds:
            return _SeriesLookup(candidate=candidate)
        # Keep the first rejection: candidates arrive best-first, so it's the
        # one the user would otherwise have seen written to the catalog.
        if rejection is None:
            rejection = verdict.reason
        logger.debug(
            "series backfill: rejected series %r for book %s: %s",
            candidate.metadata.series,
            record.id,
            verdict.reason,
        )
    return _SeriesLookup(candidate=None, rejection=rejection)


def _series_fields_and_provenance(
    candidate: MetadataCandidate,
    book_title: str | None,
    *,
    identity_confirmed: bool,
) -> tuple[dict, dict[str, str]]:
    """Extract only series/series_index plus their per-field provenance.

    A position that merely echoes a "Book N" prefix in our own title is dropped
    unless identity came from an ISBN: the provider returned that book *because*
    the query said "Book N", so the agreement is an artifact of the search, not
    evidence about where this book sits. A missing index beats a wrong one.
    """
    meta = candidate.metadata
    fields: dict = {"series": meta.series}
    provenance = {"series": meta.identifiers.get("provenance_series", candidate.source)}
    index = meta.series_index
    if (
        index is not None
        and not identity_confirmed
        and leading_book_number(book_title or "") == index
    ):
        logger.debug(
            "series backfill: dropped series index %g echoing the 'Book N' prefix in %r",
            index,
            book_title,
        )
        index = None
    if index is not None:
        fields["series_index"] = index
        provenance["series_index"] = meta.identifiers.get(
            "provenance_series_index", candidate.source
        )
    return fields, provenance


def _series_meta_matches(record: BookRecord, current: tuple[str | None, float | None]) -> bool:
    """Compare catalog series meta against a file's, index via %g on both sides.

    The file value went through %g formatting on write (6 significant digits),
    so comparing raw floats would flag high-precision catalog indices as
    forever-stale and rewrite them every run.
    """

    def key(value: float | None) -> str | None:
        return None if value is None else f"{value:g}"

    return current[0] == record.metadata.series and key(current[1]) == key(
        record.metadata.series_index
    )


def _stale_epub_records(
    records: list[BookRecord],
) -> tuple[list[BookRecord], list[tuple[BookRecord, Exception]]]:
    """Split books into stale-EPUB ones and ones whose EPUB could not be read.

    Stale means the library EPUB's series meta doesn't match the catalog. The
    unreadable list is returned rather than swallowed so the caller can name
    each skipped book — a silently skipped book never gets repaired and never
    tells anyone why.
    """
    stale: list[BookRecord] = []
    unreadable: list[tuple[BookRecord, Exception]] = []
    for record in records:
        if not record.metadata.series:
            continue
        out = record.output_path
        if out is None or out.suffix.lower() != ".epub" or not out.exists():
            continue
        try:
            current = read_calibre_series(out)
        except _EPUB_SCAN_ERRORS as exc:
            unreadable.append((record, exc))
            continue
        if not _series_meta_matches(record, current):
            stale.append(record)
    return stale, unreadable


def _write_series_epub(catalog: LibraryCatalog, record: BookRecord) -> list[str]:
    """Rewrite one library EPUB atomically; return the fields that failed verify.

    Same pattern as `authors fix-sort`: write to a sibling temp file, verify,
    then ``os.replace`` swaps it in. An empty list means the swap happened.
    A failed verify leaves the original untouched.

    Verification covers every field ``write_epub_metadata`` touches, not just
    series: the write re-serializes the whole OPF/NCX through ebooklib, so a
    series-only check could wave through a file that lost its title.
    """
    src = record.output_path
    assert src is not None  # guaranteed by _stale_epub_records
    tmp = src.with_name(src.name + ".fixtmp")
    shutil.copy2(src, tmp)
    try:
        write_epub_metadata(tmp, record.metadata)
        failed = [v.field for v in _verify_write(tmp, record.metadata) if not v.passed]
        if failed:
            tmp.unlink(missing_ok=True)
            return failed
        os.replace(tmp, src)
    except _EPUB_WRITE_ERRORS:
        tmp.unlink(missing_ok=True)
        raise

    # The swap already succeeded, so a hashing failure is not a failed write.
    # Report it and leave the stale hash for `verify` to flag rather than
    # telling the user the rewrite failed when the file is in place.
    try:
        catalog.update_book(record.id, file_hash=compute_file_hash(src))
    except OSError as exc:
        logger.warning("series backfill: could not rehash %s after write: %s", src, exc)
    return []


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
            lookup = _find_series_candidate(provider, record, threshold)
            if lookup.candidate is not None:
                fields, provenance = _series_fields_and_provenance(
                    lookup.candidate,
                    title,
                    identity_confirmed=lookup.identity_confirmed,
                )
                source = provenance["series"]
            else:
                guess = infer_series_from_title(title or "")
                if guess is None:
                    # Name the rejected candidate rather than just "no series
                    # found" — otherwise a book that had a series available and
                    # declined it looks identical to one nobody knew about.
                    why = f": {lookup.rejection}" if lookup.rejection else ""
                    console.print(f"  [dim]{record.id} {title}: no series found{why}[/dim]")
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
        stale, unreadable = _stale_epub_records(
            _select_books(catalog, book_id, backfill_all, tag_name)
        )
        for record, exc in unreadable:
            console.print(
                f"  [yellow]{record.id} {record.metadata.title}: "
                f"unreadable EPUB, skipped: {exc}[/yellow]"
            )
        if dry_run:
            if stale:
                console.print(
                    f"[dim]dry-run:[/dim] {len(stale)} EPUB file(s) would be rewritten "
                    "with series metadata."
                )
        else:
            rewritten = 0
            failed_writes = 0
            for record in stale:
                try:
                    failed_fields = _write_series_epub(catalog, record)
                except _EPUB_WRITE_ERRORS as exc:
                    console.print(
                        f"  [red]{record.id} {record.metadata.title}: "
                        f"EPUB write failed: {exc}[/red]"
                    )
                    failed_writes += 1
                    continue
                if failed_fields:
                    failed_writes += 1
                    console.print(
                        f"  [red]{record.id} {record.metadata.title}: verify failed "
                        f"({', '.join(failed_fields)}); original kept[/red]"
                    )
                else:
                    rewritten += 1
            # Printed even at zero so a run that rewrote nothing says so.
            msg = f"Updated series metadata in [green]{rewritten}[/green] EPUB file(s)."
            if failed_writes:
                msg += f" [red]{failed_writes} failed.[/red]"
            console.print(msg)
    finally:
        conn.close()

    label = "would fill" if dry_run else "filled"
    console.print(f"\nDone: [green]{filled} {label}[/green], [yellow]{missed} unresolved[/yellow]")
