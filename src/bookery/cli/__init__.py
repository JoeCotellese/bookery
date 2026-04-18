# ABOUTME: CLI package for Bookery, built on Click.
# ABOUTME: Defines the root command group and registers subcommands.

import logging

import click

from bookery.cli.commands import (
    add_cmd,
    convert_cmd,
    folder_cmd,
    genre_cmd,
    import_cmd,
    info_cmd,
    inspect_cmd,
    inventory_cmd,
    ls_cmd,
    match_cmd,
    rematch_cmd,
    search_cmd,
    serve_cmd,
    sync_cmd,
    tag_cmd,
    vault_export_cmd,
    verify_cmd,
)


@click.group()
@click.version_option(package_name="bookery")
@click.option("-v", "--verbose", count=True, help="Increase verbosity (-v info, -vv debug).")
def cli(verbose: int) -> None:
    """Bookery - a CLI-first ebook library manager."""
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
cli.add_command(convert_cmd.convert)
cli.add_command(folder_cmd.folder)
cli.add_command(genre_cmd.genre)
cli.add_command(import_cmd.import_command)
cli.add_command(info_cmd.info)
cli.add_command(inspect_cmd.inspect)
cli.add_command(inventory_cmd.inventory)
cli.add_command(ls_cmd.ls)
cli.add_command(match_cmd.match)
cli.add_command(rematch_cmd.rematch)
cli.add_command(search_cmd.search)
cli.add_command(serve_cmd.serve)
cli.add_command(sync_cmd.sync)
cli.add_command(tag_cmd.tag)
cli.add_command(vault_export_cmd.vault_export)
cli.add_command(verify_cmd.verify)
