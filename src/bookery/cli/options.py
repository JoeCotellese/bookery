# ABOUTME: Shared Click options for Bookery CLI commands.
# ABOUTME: Provides reusable decorators for --db, --yes, --threshold, and their resolvers.

from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from bookery.db.connection import DEFAULT_DB_PATH


def resolve_db_path(db_path: Path | None) -> Path:
    """Resolve the effective database path.

    Precedence: subcommand --db > top-level --db (ctx.obj) > DEFAULT_DB_PATH.
    """
    if db_path is not None:
        return db_path
    ctx = click.get_current_context(silent=True)
    if ctx is not None:
        obj = ctx.find_root().obj
        if isinstance(obj, dict):
            top = obj.get("db_path")
            if top is not None:
                return top
    return DEFAULT_DB_PATH


db_option = click.option(
    "--db",
    "db_path",
    type=click.Path(path_type=Path),
    default=None,
    help=f"Override library database path (default: top-level --db or {DEFAULT_DB_PATH}).",
)


def _deprecated_quiet_callback(
    _ctx: click.Context, _param: click.Parameter, value: bool,
) -> bool:
    if value:
        click.echo(
            "warning: -q/--quiet is deprecated; use -y/--yes instead.",
            err=True,
        )
    return value


def auto_accept_option(func: Callable[..., Any]) -> Callable[..., Any]:
    """Attach `-y/--yes` (canonical) and `-q/--quiet` (deprecated alias).

    Both feed the same `auto_accept` parameter. Using `-q/--quiet` prints
    a deprecation warning to stderr.
    """
    func = click.option(
        "-q",
        "--quiet",
        "auto_accept",
        is_flag=True,
        default=False,
        hidden=True,
        expose_value=True,
        callback=_deprecated_quiet_callback,
        help="Deprecated alias for --yes.",
    )(func)
    func = click.option(
        "-y",
        "--yes",
        "auto_accept",
        is_flag=True,
        default=False,
        help="Auto-accept high-confidence matches without prompting.",
    )(func)
    return func


def _resolve_threshold_default() -> float:
    from bookery.core.config import get_matching_config
    return get_matching_config().auto_accept_threshold


threshold_option = click.option(
    "-t",
    "--threshold",
    type=click.FloatRange(0.0, 1.0),
    default=_resolve_threshold_default,
    show_default="from [matching].auto_accept_threshold",
    help=(
        "Confidence cutoff for auto-accept (0.0-1.0). "
        "Default is [matching].auto_accept_threshold in config (0.8)."
    ),
)
