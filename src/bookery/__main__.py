# ABOUTME: Entry point for `python -m bookery` invocation.
# ABOUTME: Delegates to the Click CLI group.

from bookery.cli import cli

if __name__ == "__main__":
    cli()
