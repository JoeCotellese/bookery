# ABOUTME: The `bookery add` command for one-shot single-file EPUB import.
# ABOUTME: Thin wrapper over import_books that copies a file into the library and catalogs it.

from pathlib import Path

import click
from rich.console import Console

from bookery.cli._match_helpers import (
    build_match_fn,
    build_progress_fn,
    format_skip_breakdown,
)
from bookery.cli.options import db_option
from bookery.core.config import get_library_root
from bookery.core.importer import MatchFn, import_books
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import DEFAULT_DB_PATH, open_library

console = Console()


def _is_inside(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False


@click.command("add")
@click.argument(
    "file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@db_option
@click.option(
    "--move",
    "do_move",
    is_flag=True,
    default=False,
    help="Delete source file after successful catalog (library copy is preserved).",
)
@click.option(
    "--no-match",
    "no_match",
    is_flag=True,
    default=False,
    help="Skip the metadata matching pipeline.",
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
    default=0.8,
    help="Confidence cutoff for auto-accept (0.0-1.0, default 0.8).",
)
def add_command(
    file: Path,
    db_path: Path | None,
    do_move: bool,
    no_match: bool,
    quiet: bool,
    threshold: float,
) -> None:
    """Add a single EPUB to the library in one step.

    Copies FILE into the configured library_root, runs the match
    pipeline (unless --no-match), and catalogs the book. The source
    file is preserved by default; use --move to delete it after a
    successful catalog insert.
    """
    if file.suffix.lower() != ".epub":
        raise click.BadParameter(
            f"{file.name} is not an EPUB file.", param_hint="FILE",
        )

    # --no-match with --quiet / non-default --threshold is a flag conflict
    if no_match and (quiet or threshold != 0.8):
        console.print(
            "[yellow]warning:[/yellow] --quiet/--threshold ignored with --no-match",
        )

    library_root = get_library_root()
    # TODO: wrap conn in try-finally or context manager to prevent leak on exception
    conn = open_library(db_path or DEFAULT_DB_PATH)
    catalog = LibraryCatalog(conn)

    match_fn: MatchFn | None = None
    if not no_match:
        match_fn = build_match_fn(
            console=console,
            output_dir=library_root,
            quiet=quiet,
            threshold=threshold,
        )

    idempotent = _is_inside(file, library_root)
    if not idempotent:
        console.print(
            f"Copying to [bold]{library_root}[/bold]…",
        )

    on_progress = build_progress_fn(console)

    result = import_books(
        [file], catalog,
        library_root=library_root,
        match_fn=match_fn,
        move=do_move,
        on_progress=on_progress,
    )

    # Summary
    console.print()
    parts = []
    if result.added:
        parts.append(f"[green]{result.added} added[/green]")
    if result.skipped:
        parts.append(f"[yellow]{format_skip_breakdown(result)}[/yellow]")
    if result.errors:
        parts.append(f"[red]{result.errors} error(s)[/red]")

    if parts:
        console.print(", ".join(parts))

    if result.error_details:
        console.print(
            f"\n[yellow]{result.errors} file(s) could not be read:[/yellow]"
        )
        for path, msg in result.error_details:
            console.print(f"  [dim]{path.name}:[/dim] {msg}")

    conn.close()

    if result.errors:
        raise click.exceptions.Exit(1)
