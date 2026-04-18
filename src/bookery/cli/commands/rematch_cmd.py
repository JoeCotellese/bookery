# ABOUTME: The `bookery rematch` command for re-running metadata matching on cataloged books.
# ABOUTME: Updates DB records with enriched metadata from Open Library.

import logging
from pathlib import Path

import click
from rich.console import Console

from bookery.cli.options import db_option
from bookery.cli.review import ReviewSession
from bookery.core.config import get_library_root
from bookery.core.pipeline import match_one
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import DEFAULT_DB_PATH, open_library
from bookery.db.mapping import BookRecord
from bookery.metadata.http import BookeryHttpClient
from bookery.metadata.openlibrary import OpenLibraryProvider
from bookery.metadata.types import BookMetadata

logger = logging.getLogger(__name__)


def _create_provider() -> OpenLibraryProvider:
    """Create the default metadata provider (Open Library)."""
    http_client = BookeryHttpClient()
    return OpenLibraryProvider(http_client=http_client)


def _validate_selectors(
    book_id: int | None, match_all: bool, tag_name: str | None,
) -> None:
    """Validate that exactly one selector is specified.

    Raises:
        click.UsageError: If zero or more than one selector is given.
    """
    count = sum([book_id is not None, match_all, tag_name is not None])
    if count != 1:
        raise click.UsageError(
            "Specify exactly one of: BOOK_ID, --all, or --tag."
        )


def _select_books(
    catalog: LibraryCatalog,
    book_id: int | None,
    match_all: bool,
    tag_name: str | None,
) -> list[BookRecord]:
    """Select books from the catalog based on the given selector.

    Returns:
        List of BookRecord objects. Empty list if book_id not found.

    Raises:
        ValueError: If tag_name doesn't exist in the catalog.
    """
    if book_id is not None:
        record = catalog.get_by_id(book_id)
        return [record] if record else []

    if match_all:
        return catalog.list_all()

    if tag_name is not None:
        return catalog.get_books_by_tag(tag_name)

    return []


def _metadata_to_update_fields(metadata: BookMetadata) -> dict:
    """Extract non-None fields from metadata as a dict for catalog.update_book().

    Only includes fields that are meaningful for DB update.
    """
    fields: dict = {}
    if metadata.title:
        fields["title"] = metadata.title
    if metadata.authors:
        fields["authors"] = metadata.authors
    if metadata.author_sort:
        fields["author_sort"] = metadata.author_sort
    if metadata.isbn:
        fields["isbn"] = metadata.isbn
    if metadata.language:
        fields["language"] = metadata.language
    if metadata.publisher:
        fields["publisher"] = metadata.publisher
    if metadata.description:
        fields["description"] = metadata.description
    if metadata.series:
        fields["series"] = metadata.series
    if metadata.series_index is not None:
        fields["series_index"] = metadata.series_index
    return fields


@click.command()
@click.argument("book_id", type=int, required=False, default=None)
@click.option("--all", "match_all", is_flag=True, help="Rematch all books.")
@click.option("--tag", "tag_name", type=str, help="Rematch books with this tag.")
@db_option
@click.option(
    "-o", "--output-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Directory for modified copies (default: configured library_root).",
)
@click.option(
    "-q", "--quiet",
    is_flag=True,
    default=False,
    help="Auto-accept high-confidence matches without prompting.",
)
@click.option(
    "-t", "--threshold",
    type=click.FloatRange(0.0, 1.0),
    default=0.85,
    help="Confidence cutoff for auto-accept (0.0-1.0, default 0.85).",
)
@click.option(
    "--resume/--no-resume",
    default=True,
    help="Skip books that already have an output_path (default: --resume).",
)
def rematch(
    book_id: int | None,
    match_all: bool,
    tag_name: str | None,
    db_path: Path | None,
    output_dir: Path | None,
    quiet: bool,
    threshold: float,
    resume: bool,
) -> None:
    """Re-run metadata matching on cataloged books and update the database."""
    console = Console()

    _validate_selectors(book_id, match_all, tag_name)

    if output_dir is None:
        output_dir = get_library_root()

    conn = open_library(db_path or DEFAULT_DB_PATH)
    try:
        catalog = LibraryCatalog(conn)

        try:
            books = _select_books(catalog, book_id, match_all, tag_name)
        except ValueError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            return

        if not books:
            if book_id is not None:
                console.print(f"[red]Error:[/red] Book with id {book_id} not found.")
            else:
                console.print("[yellow]No books to rematch.[/yellow]")
            return

        # Resume: filter out books that already have output_path
        if resume:
            original_count = len(books)
            books = [b for b in books if b.output_path is None]
            skipped_resume = original_count - len(books)
            if skipped_resume:
                console.print(
                    f"[dim]Skipping {skipped_resume} already-matched "
                    f"book{'s' if skipped_resume != 1 else ''} "
                    f"(use --no-resume to reprocess).[/dim]"
                )
            if not books:
                console.print("[green]All books already matched.[/green]")
                return

        # Set up match pipeline
        provider = _create_provider()
        review = ReviewSession(
            console=console,
            quiet=quiet,
            threshold=threshold,
            lookup_fn=provider.lookup_by_url,
        )

        matched = 0
        skipped = 0
        errors = 0
        total = len(books)

        for i, record in enumerate(books, start=1):
            if not quiet:
                console.print(
                    f"\n[bold][{i}/{total}] Rematching:[/bold] "
                    f"{record.metadata.title} (id={record.id})"
                )

            if not record.source_path.exists():
                console.print(
                    f"  [red]Source file missing:[/red] {record.source_path}"
                )
                errors += 1
                continue

            result = match_one(record.source_path, provider, review, output_dir)

            if not quiet and result.normalization and result.normalization.was_modified:
                console.print(
                    f"  [dim]Normalized:[/dim] "
                    f"{result.normalization.normalized.title}"
                )

            if result.status == "matched":
                assert result.metadata is not None
                fields = _metadata_to_update_fields(result.metadata)
                catalog.update_book(record.id, **fields)
                if result.output_path:
                    catalog.set_output_path(record.id, result.output_path)
                if not quiet:
                    console.print(f"  [green]Updated:[/green] {result.output_path}")
                matched += 1
            elif result.status == "skipped":
                skipped += 1
            elif result.status == "error":
                if not quiet:
                    console.print(f"  [red]Error:[/red] {result.error}")
                errors += 1
    finally:
        conn.close()

    # Summary
    parts = []
    if matched:
        parts.append(f"[green]{matched} matched[/green]")
    if skipped:
        parts.append(f"[yellow]{skipped} skipped[/yellow]")
    if errors:
        parts.append(f"[red]{errors} error{'s' if errors != 1 else ''}[/red]")

    console.print(f"\nDone: {', '.join(parts)}")
