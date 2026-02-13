# ABOUTME: The `bookery inventory` command for scanning ebook format coverage.
# ABOUTME: Walks a directory tree and reports which books are missing a target format.

import json as json_lib
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from bookery.core.scanner import scan_directory

console = Console()


@click.command("inventory")
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--format",
    "target_format",
    default="epub",
    help="Target format to check for (default: epub).",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    default=False,
    help="Output results as JSON.",
)
def inventory(path: Path, target_format: str, json_output: bool) -> None:
    """Scan a directory tree and report ebook format coverage."""
    result = scan_directory(path)

    # Normalize target format for display and matching
    target_ext = target_format.lower() if target_format.startswith(".") else f".{target_format.lower()}"
    target_label = target_format.upper().lstrip(".")

    missing = result.missing_format(target_ext)

    if json_output:
        _print_json(result, missing, target_ext, path)
        return

    _print_rich(result, missing, target_label, path)


def _print_json(result, missing, target_ext, path):
    """Print scan results as JSON."""
    data = {
        "scan_root": str(path),
        "total_books": result.total_books,
        "format_counts": result.format_counts,
        "missing": {
            "target_format": target_ext,
            "count": len(missing),
            "books": [
                {
                    "name": book.name,
                    "directory": str(book.directory),
                    "author": book.author,
                    "title": book.title,
                    "formats": sorted(book.formats),
                }
                for book in missing
            ],
        },
        "db_cross_reference": None,
    }
    click.echo(json_lib.dumps(data, indent=2))


def _print_rich(result, missing, target_label, path):
    """Print scan results with Rich formatting."""
    if result.total_books == 0:
        console.print(f"[dim]0 book(s) scanned in {path}[/dim]")
        return

    # Format summary table
    table = Table(title="Format Summary")
    table.add_column("Extension", style="bold")
    table.add_column("Count", justify="right")

    for ext in sorted(result.format_counts):
        table.add_row(ext, str(result.format_counts[ext]))

    console.print(table)

    # Missing books
    console.print(
        f"\n[bold]{result.total_books} book(s) scanned, "
        f"{len(missing)} missing {target_label}.[/bold]"
    )

    if missing:
        console.print(f"\n[yellow]Books missing {target_label}:[/yellow]")
        for book in missing:
            formats_str = ", ".join(sorted(book.formats))
            console.print(f"  {book.name} [{formats_str}]")
