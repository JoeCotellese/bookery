# ABOUTME: Shared Click options for Bookery CLI commands.
# ABOUTME: Provides reusable decorators for common flags like --db.

from pathlib import Path

import click

from bookery.db.connection import DEFAULT_DB_PATH

db_option = click.option(
    "--db",
    "db_path",
    type=click.Path(path_type=Path),
    default=None,
    help=f"Path to library database (default: {DEFAULT_DB_PATH})",
)
