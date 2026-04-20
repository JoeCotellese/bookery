# ABOUTME: The `bookery import` command for scanning and cataloging EPUBs.
# ABOUTME: Walks a directory, extracts metadata, and stores records in the library DB.

import tempfile
from pathlib import Path

import click
from rich.console import Console

from bookery.cli._match_helpers import (
    build_match_fn,
    build_progress_fn,
    format_skip_breakdown,
)
from bookery.cli._pdf_support import convert_pdf_to_epub
from bookery.cli.options import (
    auto_accept_option,
    db_option,
    resolve_db_path,
    threshold_option,
)
from bookery.convert.errors import ConvertError
from bookery.core.config import get_library_root
from bookery.core.dedup import filter_redundant_mobis
from bookery.core.importer import MatchFn, import_books
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library

console = Console()  # TODO: move Console() inside command for testability


def _find_epubs(directory: Path) -> list[Path]:
    """Recursively find all .epub files in a directory."""
    return sorted(directory.rglob("*.epub"))


def _find_mobis(directory: Path) -> list[Path]:
    """Recursively find all .mobi files in a directory."""
    return sorted(directory.rglob("*.mobi"))


def _find_pdfs(directory: Path) -> list[Path]:
    """Recursively find real text-based PDFs (suffix + magic bytes)."""
    from bookery.cli._dispatch import UnknownFormatError, detect_source_format

    candidates = sorted(directory.rglob("*.pdf"))
    confirmed: list[Path] = []
    for path in candidates:
        try:
            if detect_source_format(path) == "pdf":
                confirmed.append(path)
        except UnknownFormatError:
            continue
    return confirmed


def _convert_pdfs(
    pdf_files: list[Path],
    tempdir: Path,
) -> tuple[list[Path], list[tuple[Path, str]]]:
    """Convert PDFs to EPUBs under tempdir; return EPUB paths + per-file errors."""
    epubs: list[Path] = []
    failures: list[tuple[Path, str]] = []
    total = len(pdf_files)
    console.print(f"Converting [bold]{total}[/bold] PDF file(s)…\n")
    for i, pdf in enumerate(pdf_files, 1):
        console.print(f"  [{i}/{total}] {pdf.name}… ", end="")
        try:
            pair_dir = tempdir / f"pdf_{i:04d}"
            pair_dir.mkdir(parents=True, exist_ok=True)
            epub_path = convert_pdf_to_epub(pdf, pair_dir, console=console)
            epubs.append(epub_path)
            console.print("[green]done[/green]")
        except ConvertError as exc:
            failures.append((pdf, str(exc)))
            console.print(f"[red]failed:[/red] {exc}")
    return epubs, failures


def _convert_mobis(
    mobi_files: list[Path],
    epub_files: list[Path],
    output_dir: Path | None,
) -> list[Path]:
    """Convert MOBI files to EPUB and extend the epub_files list.

    Lazy-imports convert_one so the import command doesn't pay for
    converter dependencies when --convert is not used.
    """
    from bookery.core.converter import convert_one

    resolved_output = output_dir or get_library_root()
    total = len(mobi_files)
    converted = 0
    skipped = 0
    failed = 0

    console.print(f"Converting [bold]{total}[/bold] MOBI file(s)…\n")

    for i, mobi_path in enumerate(mobi_files, 1):
        console.print(
            f"  [{i}/{total}] {mobi_path.name}… ", end="",
        )
        result = convert_one(mobi_path, resolved_output, force=False)
        if result.skipped and result.epub_path:
            epub_files.append(result.epub_path)
            skipped += 1
            console.print("[dim]skipped (already converted)[/dim]")
        elif result.skipped:
            # Manifest says processed but EPUB path not recoverable
            skipped += 1
            console.print("[dim]skipped (already converted, path unknown)[/dim]")
        elif result.success and result.epub_path:
            epub_files.append(result.epub_path)
            converted += 1
            console.print("[green]done[/green]")
        else:
            failed += 1
            console.print(f"[red]failed:[/red] {result.error}")

    # Summary line
    parts = []
    if converted:
        parts.append(f"[green]{converted} converted[/green]")
    if skipped:
        parts.append(f"[dim]{skipped} skipped[/dim]")
    if failed:
        parts.append(f"[red]{failed} failed[/red]")
    console.print(f"\nConversion: {', '.join(parts)}")
    console.print(
        f"Converted [bold]{converted + skipped}[/bold] of "
        f"[bold]{total}[/bold] MOBI file(s)\n",
    )
    return epub_files




@click.command("import")
@click.argument(
    "directory",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@db_option
@click.option(
    "--match/--no-match",
    "do_match",
    default=False,
    help="Run metadata matching pipeline before cataloging.",
)
@click.option(
    "-o", "--output-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Directory for modified copies (default: configured library_root).",
)
@auto_accept_option
@threshold_option
@click.option(
    "--convert/--no-convert",
    "do_convert",
    default=False,
    help="Convert MOBI files to EPUB before importing.",
)
@click.option(
    "--force-duplicates",
    is_flag=True,
    default=False,
    help="Import metadata duplicates (same ISBN or title+author) instead of skipping.",
)
@click.option(
    "--move",
    "do_move",
    is_flag=True,
    default=False,
    help="Delete source file after successful catalog (library copy is preserved).",
)
def import_command(
    directory: Path,
    db_path: Path | None,
    do_match: bool,
    output_dir: Path | None,
    auto_accept: bool,
    threshold: float,
    do_convert: bool,
    force_duplicates: bool,
    do_move: bool,
) -> None:
    """Scan a directory for EPUB files and catalog them in the library."""
    epub_files = _find_epubs(directory)
    pdf_epubs: list[Path] = []
    pdf_tempdir_ctx: tempfile.TemporaryDirectory[str] | None = None

    if do_convert:
        mobi_files = _find_mobis(directory)
        if mobi_files:
            mobi_files, dedup_skipped = filter_redundant_mobis(
                mobi_files, epub_files,
            )
            if dedup_skipped:
                console.print(
                    f"Skipped {len(dedup_skipped)} MOBI file(s) "
                    f"— EPUB exists in directory\n",
                )
        if mobi_files:
            epub_files = _convert_mobis(mobi_files, epub_files, output_dir)

    pdf_files = _find_pdfs(directory)
    if pdf_files:
        if do_move:
            console.print(
                "[yellow]warning:[/yellow] --move ignored for PDF inputs — "
                "source PDFs are preserved.\n"
            )
        pdf_tempdir_ctx = tempfile.TemporaryDirectory(prefix="bookery-pdf-")
        tempdir = Path(pdf_tempdir_ctx.name)
        pdf_epubs, _ = _convert_pdfs(pdf_files, tempdir)
        epub_files.extend(pdf_epubs)

    if not epub_files:
        if do_convert:
            console.print(
                f"[yellow]No EPUB or MOBI files found in {directory}[/yellow]",
            )
        else:
            console.print(
                f"[yellow]No EPUB files found in {directory}[/yellow]",
            )
        if pdf_tempdir_ctx is not None:
            pdf_tempdir_ctx.cleanup()
        return

    console.print(f"Found [bold]{len(epub_files)}[/bold] EPUB file(s)\n")

    # TODO: wrap conn in try-finally or context manager to prevent leak on exception
    conn = open_library(resolve_db_path(db_path))
    catalog = LibraryCatalog(conn)

    library_root = output_dir or get_library_root()
    match_fn: MatchFn | None = None
    if do_match:
        match_fn = build_match_fn(
            console=console,
            output_dir=library_root,
            quiet=auto_accept,
            threshold=threshold,
        )

    on_progress = build_progress_fn(console)

    # PDFs were converted from preserved sources; never attempt to delete the temp EPUBs.
    effective_move = do_move and not pdf_epubs

    result = import_books(
        epub_files, catalog,
        library_root=library_root,
        match_fn=match_fn,
        move=effective_move,
        force_duplicates=force_duplicates,
        on_progress=on_progress,
    )

    # Summary
    console.print()  # blank line before summary
    parts = []
    if result.added:
        parts.append(f"[green]{result.added} added[/green]")
    if result.skipped:
        parts.append(f"[yellow]{format_skip_breakdown(result)}[/yellow]")
    if result.forced:
        parts.append(f"[yellow]{result.forced} forced[/yellow]")
    if result.errors:
        parts.append(f"[red]{result.errors} error(s)[/red]")

    console.print(", ".join(parts))

    if result.error_details:
        console.print(
            f"\n[yellow]{result.errors} file(s) could not be read:[/yellow]"
        )
        for path, msg in result.error_details:
            console.print(f"  [dim]{path.name}:[/dim] {msg}")

    conn.close()

    if pdf_tempdir_ctx is not None:
        pdf_tempdir_ctx.cleanup()
