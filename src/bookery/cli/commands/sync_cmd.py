# ABOUTME: The `bookery sync` command group; ships `kobo` for syncing to mounted Kobo readers.
# ABOUTME: Wires the device/ subsystem (detect_mounted_kobo + sync_library_to_kobo) to the CLI.

from pathlib import Path

import click
from rich.console import Console

from bookery.cli.options import db_option
from bookery.core.config import get_data_dir, get_sync_config
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import DEFAULT_DB_PATH, open_library
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

    conn = open_library(db_path or DEFAULT_DB_PATH)
    try:
        catalog = LibraryCatalog(conn)
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
            )
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
        console.print(f"[red]Failed {len(report.failed)}:[/red]")
        for path, reason in report.failed:
            console.print(f"  [red]- {path.name}: {reason}[/red]")
        raise SystemExit(1)
