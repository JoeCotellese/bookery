# ABOUTME: CLI package for Bookery, built on Click.
# ABOUTME: Defines the root command group and registers subcommands.

import logging
from pathlib import Path

import click

from bookery.cli.commands import (
    add_cmd,
    authors_cmd,
    collection_cmd,
    convert_cmd,
    genre_cmd,
    info_cmd,
    inventory_cmd,
    ls_cmd,
    mark_cmd,
    match_cmd,
    prune_cmd,
    rematch_cmd,
    remove_cmd,
    reveal_cmd,
    search_cmd,
    serve_cmd,
    sync_cmd,
    tag_cmd,
    vault_export_cmd,
    verify_cmd,
)
from bookery.cli.deprecation import deprecated_command_alias


@click.group()
@click.version_option(package_name="bookery")
@click.option("-v", "--verbose", count=True, help="Increase verbosity (-v info, -vv debug).")
@click.option(
    "--db",
    "db_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to library database. Subcommand --db overrides this.",
)
@click.pass_context
def cli(ctx: click.Context, verbose: int, db_path: Path | None) -> None:
    """Bookery - a CLI-first ebook library manager."""
    ctx.ensure_object(dict)
    if db_path is not None:
        ctx.obj["db_path"] = db_path
    if verbose >= 2:
        level = logging.DEBUG
    elif verbose >= 1:
        level = logging.INFO
    else:
        level = logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(name)s %(levelname)s: %(message)s",
    )


cli.add_command(add_cmd.add_command)
cli.add_command(authors_cmd.authors)
cli.add_command(collection_cmd.collections)
cli.add_command(convert_cmd.convert)
cli.add_command(genre_cmd.genre)
cli.add_command(info_cmd.info)
cli.add_command(inventory_cmd.inventory)
cli.add_command(ls_cmd.ls)
cli.add_command(mark_cmd.mark)
cli.add_command(match_cmd.match)
cli.add_command(prune_cmd.prune)
cli.add_command(rematch_cmd.rematch)
cli.add_command(remove_cmd.remove)
cli.add_command(reveal_cmd.reveal)
cli.add_command(search_cmd.search)
cli.add_command(serve_cmd.serve)
cli.add_command(sync_cmd.sync)
cli.add_command(tag_cmd.tag)
cli.add_command(vault_export_cmd.vault_export)
cli.add_command(verify_cmd.verify)

# Deprecated alias for the old `folder` command name. Remove after one release.
deprecated_command_alias(cli, alias="folder", canonical="reveal")

# Deprecated alias for the old `import` command name. Unified under `add`,
# which now dispatches on file-vs-directory paths. Remove after one release.
deprecated_command_alias(cli, alias="import", canonical="add")

# Deprecated alias for the old `inspect` command name. Unified under `info`,
# which now dispatches on cataloged-ID vs path-to-loose-file. Remove after
# one release.
deprecated_command_alias(cli, alias="inspect", canonical="info")
