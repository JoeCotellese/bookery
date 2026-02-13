# ABOUTME: The `bookery inventory` command for scanning ebook format coverage.
# ABOUTME: Walks a directory tree and reports which books are missing a target format.

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
def inventory(path: Path, target_format: str) -> None:
    """Scan a directory tree and report ebook format coverage."""
    result = scan_directory(path)

    # Normalize target format for display and matching
    target_ext = target_format.lower() if target_format.startswith(".") else f".{target_format.lower()}"
    target_label = target_format.upper().lstrip(".")

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
    missing = result.missing_format(target_ext)
    console.print(
        f"\n[bold]{result.total_books} book(s) scanned, "
        f"{len(missing)} missing {target_label}.[/bold]"
    )

    if missing:
        console.print(f"\n[yellow]Books missing {target_label}:[/yellow]")
        for book in missing:
            formats_str = ", ".join(sorted(book.formats))
            console.print(f"  {book.name} [{formats_str}]")
