# ABOUTME: Shared helpers for wiring PDF conversion into add/import commands.
# ABOUTME: Wraps match callbacks to capture output paths so sibling .kepub.epub lands alongside.

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from rich.console import Console

from bookery.core.filecopy import copy_file
from bookery.core.importer import MatchFn, MatchResult
from bookery.core.pdf_converter import convert_pdf
from bookery.metadata.types import BookMetadata


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


def wrap_match_fn_capturing_paths(
    match_fn: MatchFn | None,
) -> tuple[MatchFn | None, dict[Path, Path]]:
    """Wrap a match callback so that output_paths are recorded by their source epub."""
    if match_fn is None:
        return None, {}

    captured: dict[Path, Path] = {}

    def wrapped(extracted: BookMetadata, epub_path: Path) -> MatchResult | None:
        result = match_fn(extracted, epub_path)
        if result is not None and result.output_path is not None:
            captured[epub_path] = cast(Path, result.output_path)
        return result

    return wrapped, captured


def place_kepubs_alongside_epubs(
    pairs: list[PdfPair],
    captured: dict[Path, Path],
    console: Console,
) -> None:
    """Copy each PdfPair.kepub into the directory where its .epub was placed by match."""
    for pair in pairs:
        dest_epub = captured.get(pair.epub)
        if dest_epub is None:
            console.print(
                f"  [yellow]warning:[/yellow] metadata match did not produce an output "
                f"path for {pair.source.name}; .kepub.epub was not catalogued."
            )
            continue
        dest = dest_epub.parent / pair.kepub.name
        copy_file(pair.kepub, dest)
        console.print(f"  [green]Kobo:[/green] {dest}")
