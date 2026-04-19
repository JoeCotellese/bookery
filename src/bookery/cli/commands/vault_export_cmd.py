# ABOUTME: The `bookery vault-export` CLI command — Obsidian vault to single-file EPUB.
# ABOUTME: Reads config defaults, walks the vault, assembles markdown, and invokes pandoc.

from __future__ import annotations

from datetime import date
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

from bookery.cli._match_helpers import build_progress_fn
from bookery.cli.options import db_option
from bookery.core.config import get_library_root, load_config
from bookery.core.importer import import_books
from bookery.core.vault.assemble import assemble_vault
from bookery.core.vault.epub import (
    EpubMetadata,
    PandocMissingError,
    PandocRenderError,
    random_uuid,
    render_epub,
    stable_uuid,
)
from bookery.core.vault.walker import walk_vault
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import DEFAULT_DB_PATH, open_library

console = Console()


@click.command("vault-export")
@click.option("--vault", "vault_opt", type=click.Path(path_type=Path), default=None,
              help="Path to the Obsidian vault.")
@click.option("--folder", "folders_opt", multiple=True,
              help="Top-level folder to include (repeatable). Defaults to the whole vault.")
@click.option("-o", "--output", "output_path", type=click.Path(path_type=Path),
              default=Path("vault.epub"), show_default=True,
              help="Output EPUB path.")
@click.option("--index/--no-index", "index_opt", default=None,
              help="Append a tag index section at the end of the EPUB.")
@click.option("--index-exclude-prefix", "index_exclude_opt", multiple=True,
              help="Suppress tags starting with this prefix from the index (repeatable).")
@click.option("--index-min-count", "index_min_count_opt", type=int, default=None,
              help="Hide tags with fewer than N notes in the index.")
@click.option("--exclude-tag", "exclude_tags_opt", multiple=True,
              help="Skip any note whose frontmatter tags include this exact tag "
                   "(repeatable). Overrides vault_export.exclude_tags in config.")
@click.option("--title", "title_opt", default=None, help="EPUB title metadata.")
@click.option("--author", "author_opt", default=None, help="EPUB author metadata.")
@click.option("--uuid", "uuid_opt",
              type=click.Choice(["stable", "random"], case_sensitive=False), default=None,
              help="EPUB identifier strategy. stable=deterministic for re-sync.")
@click.option("--version-label", "version_label_opt", default=None,
              help="Version label injected into the EPUB title (default: today's date).")
@click.option("--catalog/--no-catalog", "catalog_opt", default=None,
              help="Add the exported EPUB to the bookery library so it syncs on the "
                   "next `sync kobo`. Overrides vault_export.catalog in config.")
@db_option
def vault_export(
    vault_opt: Path | None,
    folders_opt: tuple[str, ...],
    output_path: Path,
    index_opt: bool | None,
    index_exclude_opt: tuple[str, ...],
    index_min_count_opt: int | None,
    exclude_tags_opt: tuple[str, ...],
    title_opt: str | None,
    author_opt: str | None,
    uuid_opt: str | None,
    version_label_opt: str | None,
    catalog_opt: bool | None,
    db_path: Path | None,
) -> None:
    """Export an Obsidian vault to a single EPUB with a clickable TOC.

    Wiki-links `[[Note]]` and image embeds `![[asset.png]]` are resolved.
    Callouts, block references, note embeds (`![[note]]`), and Dataview
    queries are NOT resolved in this version.
    """
    cfg = load_config().vault_export

    vault_path = vault_opt or cfg.vault_path
    if vault_path is None:
        raise click.UsageError("--vault is required (or set vault_export.vault_path in config)")
    vault_path = Path(vault_path).expanduser()
    if not vault_path.is_dir():
        raise click.UsageError(f"vault path does not exist: {vault_path}")

    folders = list(folders_opt) if folders_opt else cfg.folders
    include_index = cfg.include_index if index_opt is None else index_opt
    exclude_prefixes = list(index_exclude_opt) if index_exclude_opt else cfg.index_exclude_prefixes
    min_count = index_min_count_opt if index_min_count_opt is not None else cfg.index_min_count
    exclude_tags = list(exclude_tags_opt) if exclude_tags_opt else cfg.exclude_tags
    do_catalog = cfg.catalog if catalog_opt is None else catalog_opt
    author = author_opt or cfg.default_author
    uuid_mode = (uuid_opt or cfg.uuid_mode).lower()
    version_label = version_label_opt or date.today().isoformat()

    console.print(f"Exporting vault: [bold]{vault_path}[/bold]")

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
    overall_task = overall.add_task("Walking vault", total=None)
    current_task = current.add_task("(scanning…)", total=None)

    identifier = stable_uuid(vault_path) if uuid_mode == "stable" else random_uuid()
    title = title_opt or f"{vault_path.name} Vault"
    metadata = EpubMetadata(
        title=title,
        author=author,
        identifier=identifier,
        version_label=version_label,
    )

    with Live(Group(overall, current), console=console, transient=True, refresh_per_second=10):

        def _on_walk(idx: int, total: int, path: Path) -> None:
            overall.update(overall_task, completed=idx, total=total)
            current.update(current_task, description=path.name)

        notes = walk_vault(
            vault_path,
            folders=folders or None,
            on_progress=_on_walk,
            exclude_tags=exclude_tags or None,
        )
        if not notes:
            raise click.UsageError(f"no markdown notes found in {vault_path}")

        overall.update(
            overall_task,
            description="Assembling notes",
            completed=0,
            total=len(notes),
        )

        def _on_assemble(idx: int, total: int, note_title: str) -> None:
            overall.update(overall_task, completed=idx, total=total)
            current.update(current_task, description=note_title[:60])

        assembled = assemble_vault(
            notes,
            vault_path=vault_path,
            include_index=include_index,
            index_exclude_prefixes=exclude_prefixes,
            index_min_count=min_count,
            on_progress=_on_assemble,
        )

        overall.update(overall_task, description="Rendering EPUB (pandoc)", total=None)
        current.update(current_task, description="invoking pandoc…")

        try:
            render_epub(assembled.markdown, assembled.asset_paths, metadata, output_path)
        except PandocMissingError as exc:
            raise click.ClickException(str(exc)) from exc
        except PandocRenderError as exc:
            raise click.ClickException(str(exc)) from exc

    size = output_path.stat().st_size if output_path.exists() else 0
    console.print(f"[green]✓[/green] wrote [bold]{output_path}[/bold] ({size:,} bytes)")
    console.print(
        f"notes={len(notes)}  images={len(assembled.asset_paths)}  "
        f"broken_links={assembled.broken_link_count}  "
        f"notes_without_tags={len(assembled.notes_without_tags)}"
    )
    console.print(f"identifier={identifier}")
    if include_index and assembled.notes_without_tags:
        console.print(
            f"notes without tags: {', '.join(assembled.notes_without_tags[:5])}"
            + (" …" if len(assembled.notes_without_tags) > 5 else "")
        )

    if do_catalog:
        library_root = get_library_root()
        console.print(
            f"Cataloging into [bold]{library_root}[/bold]…"
        )
        conn = open_library(db_path or DEFAULT_DB_PATH)
        try:
            catalog = LibraryCatalog(conn)
            result = import_books(
                [output_path],
                catalog,
                library_root=library_root,
                match_fn=None,
                move=False,
                on_progress=build_progress_fn(console),
            )
        finally:
            conn.close()

        parts = []
        if result.added:
            parts.append(f"[green]{result.added} added[/green]")
        if result.skipped:
            parts.append(f"[yellow]{result.skipped} skipped[/yellow]")
        if result.errors:
            parts.append(f"[red]{result.errors} error(s)[/red]")
        if parts:
            console.print(", ".join(parts))
        if result.errors:
            for path, msg in result.error_details:
                console.print(f"  [dim]{path.name}:[/dim] {msg}")
            raise click.exceptions.Exit(1)
