# ABOUTME: CLI package for Bookery, built on Click.
# ABOUTME: Defines the root command group and registers subcommands.

import click

from bookery.cli.commands import import_cmd, inspect_cmd


@click.group()
@click.version_option(package_name="bookery")
def cli() -> None:
    """Bookery - a CLI-first ebook library manager."""


cli.add_command(import_cmd.import_books)
cli.add_command(inspect_cmd.inspect)
