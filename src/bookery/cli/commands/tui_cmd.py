# ABOUTME: The `bookery tui` command for launching the interactive terminal UI.
# ABOUTME: Checks that a library database exists, then starts the Textual app.

from pathlib import Path

import click

from bookery.cli.options import db_option
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import DEFAULT_DB_PATH, open_library
from bookery.tui.app import BookeryApp


@click.command("tui")
@db_option
def tui(db_path: Path | None) -> None:
    """Launch the interactive terminal UI for browsing the library."""
    resolved = db_path or DEFAULT_DB_PATH

    if not resolved.exists():
        click.echo(f"No library found at {resolved}. Run 'bookery import' first.")
        raise SystemExit(1)

    conn = open_library(resolved)
    catalog = LibraryCatalog(conn)

    try:
        BookeryApp(catalog=catalog).run()
    finally:
        conn.close()
