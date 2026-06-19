# ABOUTME: The `bookery prune` command for deleting catalog rows whose files are gone.
# ABOUTME: Default dry-run preview; `-y/--yes` deletes orphans and relies on FK cascade.

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from bookery.cli.options import db_option, resolve_db_path
from bookery.core.prune import (
    CheckMode,
    PruneCandidate,
    PruneState,
    classify_catalog,
)
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library

console = Console()


def _state_label(state: PruneState) -> str:
    """Render a PruneState as a short, colorized table cell."""
    if state is PruneState.ORPHAN:
        return "[red]orphan[/red]"
    if state is PruneState.SOURCE_MISSING_OUTPUT_PRESENT:
        return "[yellow]source missing[/yellow]"
    return "[green]healthy[/green]"


def _action_label(state: PruneState, *, dry_run: bool) -> str:
    """Render the action that will (or would) be taken for this row."""
    if state is PruneState.ORPHAN:
        return "would delete" if dry_run else "delete"
    if state is PruneState.SOURCE_MISSING_OUTPUT_PRESENT:
        return "warn (keep)"
    return "keep"


def _render_table(candidates: list[PruneCandidate], *, dry_run: bool) -> Table:
    """Build the Rich preview/result table for a prune run."""
    table = Table(title="Prune candidates")
    table.add_column("ID", style="dim", width=6, justify="right")
    table.add_column("Title", style="bold")
    table.add_column("Source", style="dim")
    table.add_column("Output", style="dim")
    table.add_column("State")
    table.add_column("Action")

    for candidate in candidates:
        table.add_row(
            str(candidate.record.id),
            candidate.record.metadata.title,
            "ok" if candidate.source_exists else "[red]missing[/red]",
            (
                "n/a"
                if candidate.record.output_path is None
                else "ok"
                if candidate.output_exists
                else "[red]missing[/red]"
            ),
            _state_label(candidate.state),
            _action_label(candidate.state, dry_run=dry_run),
        )

    return table


@click.command("prune")
@db_option
@click.option(
    "--check",
    "check",
    type=click.Choice(["source", "output", "both"]),
    default="both",
    show_default=True,
    help="Which paths to test for existence when classifying rows.",
)
@click.option(
    "--dry-run/--no-dry-run",
    "dry_run",
    default=True,
    show_default=True,
    help="Preview only; do not delete any rows. Defaults to on.",
)
@click.option(
    "-y",
    "--yes",
    "auto_accept",
    is_flag=True,
    default=False,
    help="Actually delete orphan rows. Mutually exclusive with --dry-run.",
)
def prune(
    db_path: Path | None,
    check: CheckMode,
    dry_run: bool,
    auto_accept: bool,
) -> None:
    """Remove catalog rows whose underlying files are missing.

    Walks the catalog and, for each book, checks the existence of
    ``source_path`` and/or ``output_path`` (per ``--check``). Three
    states are reported:

    \b
      orphan
          All checked path(s) are missing. Eligible for deletion.
      source missing
          ``source_path`` is gone but ``output_path`` is still on disk.
          The row is kept; rewriting the source pointer is left to a
          future flag.
      healthy
          Nothing to do.

    By default the command runs in dry-run mode and prints a preview
    table. Pass ``-y/--yes`` to delete the orphan rows. Deletes cascade
    via foreign keys to ``book_tags``, ``book_genres``, and
    ``book_field_provenance``.
    """
    # Mutual exclusion: --dry-run with -y is operator error. Click's
    # boolean default means dry_run is True unless the user explicitly
    # passes --no-dry-run, so we only complain when -y was supplied and
    # --no-dry-run was not — detected here via the conflict.
    if auto_accept and dry_run:
        # If the operator passed -y, treat that as intent to mutate;
        # only block when they also passed an explicit --dry-run flag.
        ctx = click.get_current_context()
        dry_run_source = ctx.get_parameter_source("dry_run")
        if dry_run_source is click.core.ParameterSource.COMMANDLINE:
            raise click.UsageError("--dry-run and -y/--yes are mutually exclusive.")
        dry_run = False

    conn = open_library(resolve_db_path(db_path))
    try:
        catalog = LibraryCatalog(conn)
        candidates = classify_catalog(catalog, check=check)

        if not candidates:
            console.print("[green]No stale rows found.[/green]")
            return

        console.print(_render_table(candidates, dry_run=dry_run))

        orphans = [c for c in candidates if c.state is PruneState.ORPHAN]
        warnings = [c for c in candidates if c.state is PruneState.SOURCE_MISSING_OUTPUT_PRESENT]

        for candidate in warnings:
            console.print(
                f"[yellow]warning:[/yellow] book {candidate.record.id} "
                f'"{candidate.record.metadata.title}" — source missing but '
                "output present; row kept (future flag will rewrite source_path)."
            )

        if dry_run:
            console.print(
                f"\n[dim]dry-run:[/dim] {len(orphans)} orphan row(s) would be "
                f"deleted, {len(warnings)} warning(s). Re-run with -y to apply."
            )
            return

        deleted = 0
        for candidate in orphans:
            catalog.delete_book(candidate.record.id)
            deleted += 1

        console.print(
            f"\n[green]Pruned {deleted} row(s).[/green] {len(warnings)} warning(s) kept."
        )
    finally:
        conn.close()
