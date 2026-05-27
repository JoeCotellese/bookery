# ABOUTME: Shared helpers for deprecating CLI commands and options with a one-release alias.
# ABOUTME: Provides deprecated_command_alias and deprecated_option for consistent warnings.

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

import click

WARNING_TEMPLATE = (
    "warning: '{old}' is deprecated; use '{new}' instead. "
    "This alias will be removed in a future release."
)

# Module-level dedupe so a warning fires at most once per process invocation
# even when the deprecated surface is hit multiple times (e.g., a flag that
# resolves repeatedly or a command invoked in a loop). Tests reset this via
# `reset_deprecation_state`.
_emitted: set[str] = set()


def reset_deprecation_state() -> None:
    """Clear the per-process dedupe set. Intended for tests."""
    _emitted.clear()


def _emit_warning(old: str, new: str) -> None:
    """Print a deprecation warning to stderr at most once per process."""
    key = f"{old}->{new}"
    if key in _emitted:
        return
    _emitted.add(key)
    click.echo(WARNING_TEMPLATE.format(old=old, new=new), err=True)


def deprecated_command_alias(
    group: click.Group,
    *,
    alias: str,
    canonical: str,
    hidden: bool = True,
) -> click.Command:
    """Register `alias` on `group` as a deprecated forwarder to `canonical`.

    The alias command accepts arbitrary args/options (`ignore_unknown_options`
    + `UNPROCESSED` argument), prints a one-line deprecation warning to
    stderr, and then re-invokes the canonical command via `group.main` so
    Click's normal parsing, exit codes, and error surface apply identically.

    Example:
        deprecated_command_alias(cli, alias="import", canonical="add")
    """
    canonical_cmd = group.get_command(click.Context(group), canonical)
    if canonical_cmd is None:
        raise ValueError(
            f"deprecated_command_alias: canonical command '{canonical}' "
            f"not registered on group '{group.name}'"
        )

    help_text = (
        f"Deprecated alias for '{canonical}'. Use '{canonical}' instead; "
        "this alias will be removed in a future release."
    )

    @group.command(
        name=alias,
        hidden=hidden,
        help=help_text,
        short_help=f"Deprecated alias for '{canonical}'.",
        context_settings={
            "ignore_unknown_options": True,
            "allow_extra_args": True,
            "help_option_names": ["-h", "--help"],
        },
    )
    @click.argument("args", nargs=-1, type=click.UNPROCESSED)
    @click.pass_context
    def _alias(ctx: click.Context, args: tuple[str, ...]) -> None:
        _emit_warning(alias, canonical)
        # Forward to the canonical command. Use ctx.invoke on the parsed
        # subcommand so we stay inside Click's machinery — exit codes,
        # UsageError surface, and stdout/stderr behavior match the canonical
        # path exactly.
        sub_ctx = canonical_cmd.make_context(
            canonical,
            list(args),
            parent=ctx.parent,
        )
        with sub_ctx:
            result = canonical_cmd.invoke(sub_ctx)
        ctx.exit(0 if result is None else int(bool(result)))

    return _alias


def deprecated_option(
    old_names: Iterable[str],
    *,
    canonical: str,
    transform: Callable[[Any], dict[str, Any]] | None = None,
    **option_kwargs: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Declare a deprecated CLI option that maps to a canonical option/flag.

    The returned decorator adds a hidden Click option for each name in
    `old_names`. When the user supplies one of the old names, a one-line
    deprecation warning is printed to stderr and the value is translated
    into the canonical parameter(s).

    `canonical` is the human-facing canonical flag spelling (e.g.
    `'--random-ids'`) used in the warning message.

    `transform`, if provided, receives the raw value of the deprecated option
    and returns a dict of {canonical_param_name: value} entries to merge into
    the command's kwargs. The canonical_param_name is the Click parameter
    name (e.g., `'random_ids'` not `'--random-ids'`). If `transform` is
    omitted, the value is forwarded under the Click-derived name of
    `canonical` (dashes -> underscores, stripped of leading dashes).

    The canonical option itself must be declared separately by the caller —
    this helper only handles the deprecated surface.

    Example (boolean rename):
        @deprecated_option(["--old-name"], canonical="--new-name")
        @click.option("--new-name", default="")
        def cmd(new_name): ...

    Example (value-to-bool translation):
        @deprecated_option(
            ["--uuid"],
            canonical="--random-ids",
            type=click.Choice(["stable", "random"]),
            transform=lambda v: {"random_ids": v == "random"} if v is not None else {},
        )
        @click.option("--random-ids", is_flag=True, default=False)
        def cmd(random_ids): ...
    """
    old_names_list = list(old_names)
    if not old_names_list:
        raise ValueError("deprecated_option: at least one old name is required")
    primary_old = old_names_list[0]
    default_param_name = canonical.lstrip("-").replace("-", "_")

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        callback = _build_callback(
            primary_old=primary_old,
            canonical=canonical,
            transform=transform,
            default_param_name=default_param_name,
        )
        # Reserve a hidden, non-exposed param destination so Click doesn't
        # try to pass `--uuid=...` to the wrapped function.
        param_dest = f"_deprecated_{default_param_name}"
        # Build args for click.option: all old names, then a destination.
        opt_args = (*old_names_list, param_dest)
        opt_kwargs: dict[str, Any] = {
            "default": None,
            "hidden": True,
            "expose_value": False,
            "callback": callback,
            "help": f"Deprecated alias for {canonical}.",
        }
        opt_kwargs.update(option_kwargs)
        return click.option(*opt_args, **opt_kwargs)(func)

    return decorator


def _build_callback(
    *,
    primary_old: str,
    canonical: str,
    transform: Callable[[Any], dict[str, Any]] | None,
    default_param_name: str,
) -> Callable[[click.Context, click.Parameter, Any], Any]:
    """Build the Click callback that fires when a deprecated option is set."""

    def callback(ctx: click.Context, param: click.Parameter, value: Any) -> Any:
        # `value is None` means the user did not supply the deprecated option;
        # leave the canonical value untouched. For flags whose default is
        # False, treat False the same way so unused flags stay quiet.
        if value is None or value is False:
            return value
        _emit_warning(primary_old, canonical)
        mapping = (
            transform(value)
            if transform is not None
            else {default_param_name: value}
        )
        # Push translated values into the params dict that Click will pass to
        # the wrapped function. We overwrite any existing default but do not
        # clobber a value the user explicitly set on the canonical name — if
        # both old and new are given, the canonical wins (last write loses
        # for the deprecated channel because the canonical option is
        # processed after by virtue of stacking order).
        if ctx.params is None:  # pragma: no cover - defensive
            ctx.params = {}
        for key, translated in mapping.items():
            # Only overwrite when the canonical key is still at its default
            # (i.e., the user did not supply it). Click stores user-provided
            # values in ctx.params at parse time; falling back to the
            # default-driven slot lets us distinguish.
            if key not in ctx.params or ctx.params[key] in (None, False, ""):
                ctx.params[key] = translated
        return value

    return callback
