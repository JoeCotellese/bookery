# ABOUTME: CLI package for Bookery, built on Click.
# ABOUTME: Defines the root command group and registers subcommands.

import click

from bookery.cli.commands import (
    import_cmd,
    info_cmd,
    inspect_cmd,
    ls_cmd,
    match_cmd,
    search_cmd,
)


@click.group()
@click.version_option(package_name="bookery")
def cli() -> None:
    """Bookery - a CLI-first ebook library manager."""


cli.add_command(import_cmd.import_command)
cli.add_command(info_cmd.info)
cli.add_command(inspect_cmd.inspect)
cli.add_command(ls_cmd.ls)
cli.add_command(match_cmd.match)
cli.add_command(search_cmd.search)
