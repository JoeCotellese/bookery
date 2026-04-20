# ABOUTME: The `bookery rematch` command for re-running metadata matching on cataloged books.
# ABOUTME: Updates DB records with enriched metadata from Open Library.

import logging
from pathlib import Path

import click
from rich.console import Console

from bookery.cli._match_helpers import build_metadata_provider
from bookery.cli.options import (
    auto_accept_option,
    db_option,
    resolve_db_path,
    threshold_option,
)
from bookery.cli.review import ReviewSession
from bookery.core.config import get_library_root
from bookery.core.pipeline import match_one
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.db.mapping import BookRecord
from bookery.metadata.types import BookMetadata

logger = logging.getLogger(__name__)


def _create_provider(*, use_cache: bool = True):
    """Create the default metadata provider (Open Library), optionally cached."""
    return build_metadata_provider(use_cache=use_cache)


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
    if metadata.subtitle:
        fields["subtitle"] = metadata.subtitle
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
    if metadata.subjects:
        fields["subjects"] = metadata.subjects
    if metadata.published_date:
        fields["published_date"] = metadata.published_date
    if metadata.original_publication_date:
        fields["original_publication_date"] = metadata.original_publication_date
    if metadata.page_count is not None:
        fields["page_count"] = metadata.page_count
    if metadata.cover_url:
        fields["cover_url"] = metadata.cover_url
    if metadata.rating is not None:
        fields["rating"] = metadata.rating
    if metadata.ratings_count is not None:
        fields["ratings_count"] = metadata.ratings_count
    if metadata.print_type:
        fields["print_type"] = metadata.print_type
    if metadata.maturity_rating:
        fields["maturity_rating"] = metadata.maturity_rating
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
@auto_accept_option
@threshold_option
@click.option(
    "--resume/--no-resume",
    default=True,
    help="Skip books that already have an output_path (default: --resume).",
)
@click.option(
    "--no-cache",
    "no_cache",
    is_flag=True,
    help="Skip the metadata response cache and force fresh provider lookups.",
)
def rematch(
    book_id: int | None,
    match_all: bool,
    tag_name: str | None,
    db_path: Path | None,
    output_dir: Path | None,
    auto_accept: bool,
    threshold: float,
    resume: bool,
    no_cache: bool,
) -> None:
    """Re-run metadata matching on cataloged books and update the database."""
    console = Console()

    _validate_selectors(book_id, match_all, tag_name)

    if output_dir is None:
        output_dir = get_library_root()

    conn = open_library(resolve_db_path(db_path))
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
        provider = _create_provider(use_cache=not no_cache)
        review = ReviewSession(
            console=console,
            quiet=auto_accept,
            threshold=threshold,
            lookup_fn=provider.lookup_by_url,
        )

        matched = 0
        skipped = 0
        errors = 0
        total = len(books)

        for i, record in enumerate(books, start=1):
            if not auto_accept:
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

            if not auto_accept and result.normalization and result.normalization.was_modified:
                console.print(
                    f"  [dim]Normalized:[/dim] "
                    f"{result.normalization.normalized.title}"
                )

            if result.status == "matched":
                assert result.metadata is not None
                fields = _metadata_to_update_fields(result.metadata)
                source = result.metadata.identifiers.get("source") or "matcher"
                per_field_provenance = {
                    k.removeprefix("provenance_"): v
                    for k, v in result.metadata.identifiers.items()
                    if k.startswith("provenance_")
                }
                written = catalog.update_book(
                    record.id,
                    source=source,
                    provenance=per_field_provenance or None,
                    respect_locked=True,
                    **fields,
                )
                if result.output_path:
                    catalog.set_output_path(record.id, result.output_path)
                if not auto_accept:
                    locked = set(fields) - set(written)
                    if locked:
                        console.print(
                            f"  [dim]Preserved locked field(s):[/dim] {', '.join(sorted(locked))}"
                        )
                    console.print(f"  [green]Updated:[/green] {result.output_path}")
                matched += 1
            elif result.status == "skipped":
                skipped += 1
            elif result.status == "error":
                if not auto_accept:
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
