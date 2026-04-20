# ABOUTME: The `bookery sync` command group; ships `kobo` for syncing to mounted Kobo readers.
# ABOUTME: Wires the device/ subsystem (detect_mounted_kobo + sync_library_to_kobo) to the CLI.

from pathlib import Path

import click
from rich.console import Console, Group
from rich.live import Live
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from bookery.cli.options import db_option, resolve_db_path
from bookery.core.config import get_data_dir, get_sync_config
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.device.errors import DeviceError, KoboNotMounted
from bookery.device.kepub_cache import KepubCache
from bookery.device.kepubify import kepubify_version, run_kepubify
from bookery.device.kobo import detect_mounted_kobo, sync_library_to_kobo

console = Console()


@click.group("sync")
def sync() -> None:
    """Sync the library to a connected device."""


@sync.command("kobo")
@click.option(
    "--target",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to the mounted Kobo (overrides auto-detection).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be copied without touching the device.",
)
@click.option(
    "--data-dir",
    "data_dir_override",
    type=click.Path(path_type=Path),
    default=None,
    help="Override the data dir (cache location). Mostly for testing.",
)
@db_option
def sync_kobo(
    target: Path | None,
    dry_run: bool,
    data_dir_override: Path | None,
    db_path: Path | None,
) -> None:
    """Convert library EPUBs to .kepub.epub and copy to a mounted Kobo."""
    sync_cfg = get_sync_config()

    resolved_target = target
    if resolved_target is None:
        if not sync_cfg.kobo.auto_detect:
            console.print(
                "[red]No --target given and auto_detect is disabled.[/red]"
            )
            raise SystemExit(1)
        detected = detect_mounted_kobo()
        if detected is None:
            err = KoboNotMounted()
            console.print(f"[red]{err}[/red]")
            raise SystemExit(err.exit_code)
        resolved_target = detected
        console.print(f"[dim]Detected Kobo at {resolved_target}[/dim]")

    if not (resolved_target / ".kobo").exists() and not dry_run:
        console.print(
            f"[yellow]Warning:[/yellow] {resolved_target} has no .kobo/ marker."
        )

    data_dir = data_dir_override or get_data_dir()
    cache = KepubCache(data_dir / "kepub_cache.db")
    workspace_dir = data_dir / "sync-workspace"

    _stage_label = {
        "hash": "hashing",
        "convert": "converting",
        "copy": "copying",
        "cached": "cached",
        "done": "done",
    }

    overall = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        console=console,
    )
    current = Progress(
        SpinnerColumn(),
        TextColumn("[dim]└─[/dim] {task.description}"),
        console=console,
    )
    overall_task = overall.add_task("Syncing", total=None)
    current_task = current.add_task("(starting…)", total=None)
    current_state: dict[str, str] = {"title": "", "stage": ""}

    def _redraw_current() -> None:
        title = current_state["title"]
        stage = current_state["stage"]
        if title and stage:
            current.update(current_task, description=f"{title}  [dim][{stage}][/dim]")
        elif title:
            current.update(current_task, description=title)

    def _on_progress(idx: int, total: int, record) -> None:  # type: ignore[no-untyped-def]
        overall.update(overall_task, completed=idx - 1, total=total)
        current_state["title"] = record.metadata.title[:60]
        current_state["stage"] = ""
        _redraw_current()

    def _on_stage(stage: str) -> None:
        current_state["stage"] = _stage_label.get(stage, stage)
        _redraw_current()

    conn = open_library(resolve_db_path(db_path))
    try:
        catalog = LibraryCatalog(conn)
        with Live(
            Group(overall, current),
            console=console,
            transient=True,
            refresh_per_second=10,
        ):
            try:
                report = sync_library_to_kobo(
                    catalog=catalog,
                    target=resolved_target,
                    cache=cache,
                    run_kepubify=run_kepubify,
                    kepubify_version=kepubify_version,
                    workspace_dir=workspace_dir,
                    books_subdir=sync_cfg.kobo.books_subdir,
                    dry_run=dry_run,
                    on_progress=_on_progress,
                    on_stage=_on_stage,
                )
                overall.update(overall_task, completed=overall.tasks[0].total or 0)
            except DeviceError as exc:
                console.print(f"[red]{exc}[/red]")
                raise SystemExit(exc.exit_code) from exc
    finally:
        conn.close()

    label = "Would copy" if dry_run else "Copied"
    if not report.copied and not report.skipped and not report.failed:
        console.print("[dim]No books to sync.[/dim]")
        return

    if report.copied:
        console.print(f"[green]{label} {len(report.copied)} book(s):[/green]")
        for path in report.copied:
            console.print(f"  {path}")
    if report.skipped:
        console.print(f"[dim]Skipped {len(report.skipped)}:[/dim]")
        for path, reason in report.skipped:
            console.print(f"  [dim]- {path.name}: {reason}[/dim]")
    if report.failed:
        # Per-book failures are reported but don't fail the command — a stale
        # catalog entry or a single un-convertible EPUB shouldn't block a sync
        # of hundreds of other books. Hard errors (missing kepubify, no Kobo
        # detected) still exit non-zero from earlier branches.
        console.print(
            f"[yellow]Warnings: {len(report.failed)} book(s) could not be "
            "synced (catalog or EPUB issue):[/yellow]"
        )
        for path, reason in report.failed:
            console.print(f"  [yellow]- {path.name}: {reason}[/yellow]")
