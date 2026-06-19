# ABOUTME: The `bookery add` command for ingesting a single file or directory of EPUBs.
# ABOUTME: Dispatches on path type: file -> single ingest; directory -> recursive scan + ingest.

import tempfile
from pathlib import Path

import click
from rich.console import Console

from bookery.cli._dispatch import UnknownFormatError, detect_source_format
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
from bookery.core.importer import ImportResult, MatchFn, import_books
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library

console = Console()


def _is_inside(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False


def _find_epubs(directory: Path) -> list[Path]:
    """Recursively find all .epub files in a directory."""
    return sorted(directory.rglob("*.epub"))


def _find_mobis(directory: Path) -> list[Path]:
    """Recursively find all .mobi files in a directory."""
    return sorted(directory.rglob("*.mobi"))


def _find_pdfs(directory: Path) -> list[Path]:
    """Recursively find real text-based PDFs (suffix + magic bytes)."""
    candidates = sorted(directory.rglob("*.pdf"))
    confirmed: list[Path] = []
    for candidate in candidates:
        try:
            if detect_source_format(candidate) == "pdf":
                confirmed.append(candidate)
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

    Lazy-imports convert_one so directory adds don't pay for converter
    dependencies unless --convert is supplied.
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
            f"  [{i}/{total}] {mobi_path.name}… ",
            end="",
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
        f"Converted [bold]{converted + skipped}[/bold] of [bold]{total}[/bold] MOBI file(s)\n",
    )
    return epub_files


def _print_summary(result: ImportResult) -> None:
    """Render the post-ingest summary line and any per-file errors."""
    console.print()
    parts = []
    if result.added:
        parts.append(f"[green]{result.added} added[/green]")
    if result.skipped:
        parts.append(f"[yellow]{format_skip_breakdown(result)}[/yellow]")
    if result.forced:
        parts.append(f"[yellow]{result.forced} forced[/yellow]")
    if result.errors:
        parts.append(f"[red]{result.errors} error(s)[/red]")

    if parts:
        console.print(", ".join(parts))

    if result.error_details:
        console.print(f"\n[yellow]{result.errors} file(s) could not be read:[/yellow]")
        for path, msg in result.error_details:
            console.print(f"  [dim]{path.name}:[/dim] {msg}")


def _add_file(
    *,
    ctx: click.Context,
    file: Path,
    db_path: Path | None,
    do_move: bool,
    do_match: bool | None,
    auto_accept: bool,
    threshold: float,
) -> None:
    """Single-file ingest path. --match defaults to True when unset."""
    if do_match is None:
        do_match = True

    try:
        source_format = detect_source_format(file)
    except UnknownFormatError as exc:
        raise click.BadParameter(str(exc), param_hint="PATH") from exc

    # Warn when --no-match is combined with flags only meaningful to matching.
    threshold_from_cli = (
        ctx.get_parameter_source("threshold") == click.core.ParameterSource.COMMANDLINE
    )
    if not do_match and (auto_accept or threshold_from_cli):
        console.print(
            "[yellow]warning:[/yellow] --yes/--threshold ignored with --no-match",
        )

    library_root = get_library_root()
    # TODO: wrap conn in try-finally or context manager to prevent leak on exception
    conn = open_library(resolve_db_path(db_path))
    catalog = LibraryCatalog(conn)

    match_fn: MatchFn | None = None
    if do_match:
        match_fn = build_match_fn(
            console=console,
            output_dir=library_root,
            quiet=auto_accept,
            threshold=threshold,
        )

    on_progress = build_progress_fn(console)

    temp_ctx: tempfile.TemporaryDirectory[str] | None = None

    try:
        if source_format == "pdf":
            if do_move:
                console.print(
                    "[yellow]warning:[/yellow] --move ignored for PDF input — "
                    "source PDF is preserved."
                )
                do_move = False
            temp_ctx = tempfile.TemporaryDirectory(prefix="bookery-pdf-")
            tempdir = Path(temp_ctx.name)
            try:
                epub_to_import = convert_pdf_to_epub(file, tempdir, console=console)
            except ConvertError as exc:
                console.print(f"[red]error:[/red] {exc}")
                conn.close()
                raise click.exceptions.Exit(exc.exit_code) from exc
        else:
            epub_to_import = file
            idempotent = _is_inside(file, library_root)
            if not idempotent:
                console.print(
                    f"Copying to [bold]{library_root}[/bold]…",
                )

        result = import_books(
            [epub_to_import],
            catalog,
            library_root=library_root,
            match_fn=match_fn,
            move=do_move,
            on_progress=on_progress,
        )
    finally:
        if temp_ctx is not None:
            temp_ctx.cleanup()

    _print_summary(result)

    conn.close()

    if result.errors:
        raise click.exceptions.Exit(1)


def _add_directory(
    *,
    directory: Path,
    db_path: Path | None,
    do_match: bool | None,
    output_dir: Path | None,
    auto_accept: bool,
    threshold: float,
    do_convert: bool,
    force_duplicates: bool,
    do_move: bool,
) -> None:
    """Directory ingest path. --match defaults to False when unset."""
    if do_match is None:
        do_match = False

    epub_files = _find_epubs(directory)
    pdf_epubs: list[Path] = []
    pdf_tempdir_ctx: tempfile.TemporaryDirectory[str] | None = None

    if do_convert:
        mobi_files = _find_mobis(directory)
        if mobi_files:
            mobi_files, dedup_skipped = filter_redundant_mobis(
                mobi_files,
                epub_files,
            )
            if dedup_skipped:
                console.print(
                    f"Skipped {len(dedup_skipped)} MOBI file(s) — EPUB exists in directory\n",
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
        epub_files,
        catalog,
        library_root=library_root,
        match_fn=match_fn,
        move=effective_move,
        force_duplicates=force_duplicates,
        on_progress=on_progress,
    )

    _print_summary(result)

    conn.close()

    if pdf_tempdir_ctx is not None:
        pdf_tempdir_ctx.cleanup()


@click.command("add")
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=True, dir_okay=True, path_type=Path),
)
@db_option
@click.option(
    "--move",
    "do_move",
    is_flag=True,
    default=False,
    help="Delete source file(s) after successful catalog (library copy is preserved).",
)
@click.option(
    "--match/--no-match",
    "do_match",
    default=None,
    help=(
        "Run the metadata matching pipeline. Default: enabled for a single "
        "file, disabled for a directory scan."
    ),
)
@click.option(
    "-o",
    "--output-dir",
    type=click.Path(path_type=Path),
    default=None,
    help=(
        "Directory for modified copies (default: configured library_root). "
        "Only meaningful when PATH is a directory."
    ),
)
@click.option(
    "--convert/--no-convert",
    "do_convert",
    default=False,
    help=(
        "Convert MOBI files to EPUB before cataloging. Only meaningful when PATH is a directory."
    ),
)
@click.option(
    "--force-duplicates",
    is_flag=True,
    default=False,
    help=(
        "Import metadata duplicates (same ISBN or title+author) instead of "
        "skipping. Only meaningful when PATH is a directory."
    ),
)
@auto_accept_option
@threshold_option
@click.pass_context
def add_command(
    ctx: click.Context,
    path: Path,
    db_path: Path | None,
    do_move: bool,
    do_match: bool | None,
    output_dir: Path | None,
    do_convert: bool,
    force_duplicates: bool,
    auto_accept: bool,
    threshold: float,
) -> None:
    """Add a single EPUB or a directory of EPUBs to the library.

    When PATH is a file, copies it into the configured library_root, runs
    the metadata match pipeline (unless --no-match), and catalogs the book.

    When PATH is a directory, recursively discovers EPUBs (and optionally
    MOBI/PDF inputs with --convert), copies them into library_root, and
    catalogs them. The match pipeline is off by default for directory
    scans; pass --match to enable it.

    Source files are preserved by default; use --move to delete them after
    a successful catalog insert.
    """
    if path.is_dir():
        _add_directory(
            directory=path,
            db_path=db_path,
            do_match=do_match,
            output_dir=output_dir,
            auto_accept=auto_accept,
            threshold=threshold,
            do_convert=do_convert,
            force_duplicates=force_duplicates,
            do_move=do_move,
        )
        return

    # Directory-only flags are silently ignored for single-file paths.
    if output_dir is not None or do_convert or force_duplicates:
        console.print(
            "[yellow]warning:[/yellow] --output-dir/--convert/--force-duplicates "
            "have no effect on a single file and were ignored.",
        )

    _add_file(
        ctx=ctx,
        file=path,
        db_path=db_path,
        do_move=do_move,
        do_match=do_match,
        auto_accept=auto_accept,
        threshold=threshold,
    )
