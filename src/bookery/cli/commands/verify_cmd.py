# ABOUTME: The `bookery verify` command for checking library integrity.
# ABOUTME: Detects missing files and optional hash mismatches across the catalog.

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from bookery.cli.options import db_option
from bookery.core.verifier import verify_library
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import DEFAULT_DB_PATH, open_library

console = Console()  # TODO: move Console() inside command for testability


@click.command("verify")
@db_option
@click.option(
    "--check-hash",
    is_flag=True,
    default=False,
    help="Re-hash source files and compare against stored hashes.",
)
def verify(db_path: Path | None, check_hash: bool) -> None:
    """Verify library integrity: check for missing or changed files."""
    # TODO: wrap conn in try-finally or context manager to prevent leak on exception
    conn = open_library(db_path or DEFAULT_DB_PATH)
    catalog = LibraryCatalog(conn)

    result = verify_library(catalog, check_hash=check_hash)

    if result.total_issues > 0:
        table = Table()
        table.add_column("ID", style="dim", width=4)
        table.add_column("Title", style="bold")
        table.add_column("Issue", style="red")

        for record in result.missing_source:
            table.add_row(str(record.id), record.metadata.title, "Missing source")

        for record in result.missing_output:
            table.add_row(str(record.id), record.metadata.title, "Missing output")

        for record in result.hash_mismatch:
            table.add_row(str(record.id), record.metadata.title, "Hash mismatch")

        console.print(table)
        console.print(
            f"\n[red]{result.total_issues} issue(s) found, {result.ok} book(s) verified.[/red]"
        )
        conn.close()
        raise SystemExit(1)

    console.print(f"[green]All {result.ok} book(s) verified.[/green]")
    conn.close()
