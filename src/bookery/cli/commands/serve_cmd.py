# ABOUTME: The `bookery serve` command for launching the web UI.
# ABOUTME: Opens the library database and starts a Flask development server.

from pathlib import Path

import click

from bookery.cli.options import db_option
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import DEFAULT_DB_PATH, open_library
from bookery.web import create_app


@click.command("serve")
@db_option
@click.option(
    "--host",
    default="127.0.0.1",
    help="Host to bind to (default: 127.0.0.1).",
)
@click.option(
    "--port",
    default=5000,
    type=int,
    help="Port to listen on (default: 5000).",
)
def serve(db_path: Path | None, host: str, port: int) -> None:
    """Launch the web UI for browsing the library."""
    resolved = db_path or DEFAULT_DB_PATH

    if not resolved.exists():
        click.echo(f"No library found at {resolved}. Run 'bookery import' first.")
        raise SystemExit(1)

    conn = open_library(resolved, check_same_thread=False)
    catalog = LibraryCatalog(conn)

    app = create_app(catalog)
    try:
        app.run(host=host, port=port)
    finally:
        conn.close()
