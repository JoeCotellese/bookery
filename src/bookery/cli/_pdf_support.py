# ABOUTME: Shared helpers for wiring PDF conversion into add/import commands.
# ABOUTME: Locates cataloged EPUB paths by file hash so sibling .kepub.epub lands alongside.

from dataclasses import dataclass
from pathlib import Path

from rich.console import Console

from bookery.core.filecopy import copy_file
from bookery.core.pdf_converter import convert_pdf
from bookery.db.catalog import LibraryCatalog
from bookery.db.hashing import compute_file_hash


@dataclass(frozen=True)
class PdfPair:
    """Triple linking a source PDF to its temporary EPUB + KEPUB pair."""

    source: Path
    epub: Path
    kepub: Path


def convert_pdf_to_pair(
    source: Path,
    out_dir: Path,
    *,
    console: Console,
) -> PdfPair:
    """Run the PDF→EPUB→KEPUB pipeline and wrap the result as a PdfPair."""
    result = convert_pdf(source, out_dir, console=console)
    if result.warnings:
        for warning in result.warnings:
            console.print(f"  [yellow]warning:[/yellow] {warning}")
    return PdfPair(source=source, epub=result.epub_path, kepub=result.kepub_path)


def snapshot_epub_hashes(pairs: list[PdfPair]) -> dict[Path, str]:
    """Pre-compute the SHA-256 of each temp EPUB before import_books touches it."""
    return {pair.epub: compute_file_hash(pair.epub) for pair in pairs}


def place_kepubs_via_catalog(
    pairs: list[PdfPair],
    hashes: dict[Path, str],
    catalog: LibraryCatalog,
    console: Console,
) -> None:
    """Look each converted EPUB up in the catalog by hash and copy its kepub alongside."""
    for pair in pairs:
        file_hash = hashes.get(pair.epub)
        record = catalog.get_by_hash(file_hash) if file_hash else None
        output_path = getattr(record, "output_path", None) if record else None
        if output_path is None:
            console.print(
                f"  [yellow]warning:[/yellow] could not locate cataloged EPUB for "
                f"{pair.source.name}; .kepub.epub was not placed."
            )
            continue
        dest_dir = Path(output_path).parent
        dest = dest_dir / pair.kepub.name
        copy_file(pair.kepub, dest)
        console.print(f"  [green]Kobo:[/green] {dest}")
