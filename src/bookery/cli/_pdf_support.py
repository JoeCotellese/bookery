# ABOUTME: Shared helper for wiring PDF conversion into add/import commands.
# ABOUTME: Wraps convert_pdf and surfaces any warnings to the console.

from pathlib import Path

from rich.console import Console

from bookery.core.pdf_converter import convert_pdf


def convert_pdf_to_epub(
    source: Path,
    out_dir: Path,
    *,
    console: Console,
) -> Path:
    """Run the PDF→EPUB pipeline; return the produced EPUB path."""
    result = convert_pdf(source, out_dir, console=console)
    for warning in result.warnings:
        console.print(f"  [yellow]warning:[/yellow] {warning}")
    return result.epub_path
