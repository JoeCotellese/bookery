# ABOUTME: Unit tests for the shared CLI deprecation alias helper.
# ABOUTME: Covers command-level and flag-level aliases, warning dedupe, and value forwarding.

from __future__ import annotations

import click
from click.testing import CliRunner

from bookery.cli.deprecation import (
    deprecated_command_alias,
    deprecated_option,
    reset_deprecation_state,
)

# --- helpers -------------------------------------------------------------


def _make_canonical_group() -> click.Group:
    """Build a small group with one canonical command for alias tests."""

    @click.group()
    def cli() -> None:
        pass

    @cli.command("add")
    @click.argument("path", required=False)
    @click.option("--flag/--no-flag", default=False)
    @click.option("--value", default="")
    def add(path: str | None, flag: bool, value: str) -> None:
        click.echo(f"add path={path} flag={flag} value={value}")

    return cli


# --- command-level alias --------------------------------------------------


def test_canonical_command_works() -> None:
    reset_deprecation_state()
    cli = _make_canonical_group()
    runner = CliRunner()
    result = runner.invoke(cli, ["add", "book.epub", "--flag", "--value", "x"])
    assert result.exit_code == 0
    assert "add path=book.epub flag=True value=x" in result.stdout
    assert result.stderr == ""


def test_alias_forwards_args_and_options() -> None:
    reset_deprecation_state()
    cli = _make_canonical_group()
    deprecated_command_alias(cli, alias="import", canonical="add")
    runner = CliRunner()
    result = runner.invoke(cli, ["import", "book.epub", "--flag", "--value", "y"])
    assert result.exit_code == 0
    assert "add path=book.epub flag=True value=y" in result.stdout


def test_alias_prints_warning_to_stderr() -> None:
    reset_deprecation_state()
    cli = _make_canonical_group()
    deprecated_command_alias(cli, alias="import", canonical="add")
    runner = CliRunner()
    result = runner.invoke(cli, ["import", "book.epub"])
    assert result.exit_code == 0
    assert (
        "warning: 'import' is deprecated; use 'add' instead. "
        "This alias will be removed in a future release."
    ) in result.stderr
    # Warning must not pollute stdout.
    assert "deprecated" not in result.stdout


def test_alias_exit_code_matches_canonical_on_error() -> None:
    reset_deprecation_state()

    @click.group()
    def cli() -> None:
        pass

    @cli.command("add")
    def add() -> None:
        raise click.UsageError("bad input")

    deprecated_command_alias(cli, alias="import", canonical="add")
    runner = CliRunner()
    canonical = runner.invoke(cli, ["add"])
    reset_deprecation_state()
    aliased = runner.invoke(cli, ["import"])
    assert canonical.exit_code == aliased.exit_code
    assert canonical.exit_code != 0


def test_alias_help_marks_deprecation() -> None:
    reset_deprecation_state()
    cli = _make_canonical_group()
    deprecated_command_alias(cli, alias="import", canonical="add")
    runner = CliRunner()
    result = runner.invoke(cli, ["import", "--help"])
    assert result.exit_code == 0
    assert "deprecated" in result.stdout.lower()


# --- flag-level alias -----------------------------------------------------


def test_flag_alias_canonical_works() -> None:
    reset_deprecation_state()

    @click.command()
    @deprecated_option(
        ["--uuid"],
        canonical="--random-ids",
        type=click.Choice(["stable", "random"]),
        transform=lambda v: {"random_ids": v == "random"} if v is not None else {},
    )
    @click.option("--random-ids", is_flag=True, default=False)
    def cmd(random_ids: bool) -> None:
        click.echo(f"random_ids={random_ids}")

    runner = CliRunner()
    result = runner.invoke(cmd, ["--random-ids"])
    assert result.exit_code == 0
    assert "random_ids=True" in result.stdout
    assert result.stderr == ""


def test_flag_alias_translates_old_to_canonical() -> None:
    reset_deprecation_state()

    @click.command()
    @deprecated_option(
        ["--uuid"],
        canonical="--random-ids",
        type=click.Choice(["stable", "random"]),
        transform=lambda v: {"random_ids": v == "random"} if v is not None else {},
    )
    @click.option("--random-ids", is_flag=True, default=False)
    def cmd(random_ids: bool) -> None:
        click.echo(f"random_ids={random_ids}")

    runner = CliRunner()
    result = runner.invoke(cmd, ["--uuid", "random"])
    assert result.exit_code == 0
    assert "random_ids=True" in result.stdout
    assert (
        "warning: '--uuid' is deprecated; use '--random-ids' instead. "
        "This alias will be removed in a future release."
    ) in result.stderr


def test_flag_alias_stable_value_translates_to_false() -> None:
    reset_deprecation_state()

    @click.command()
    @deprecated_option(
        ["--uuid"],
        canonical="--random-ids",
        type=click.Choice(["stable", "random"]),
        transform=lambda v: {"random_ids": v == "random"} if v is not None else {},
    )
    @click.option("--random-ids", is_flag=True, default=False)
    def cmd(random_ids: bool) -> None:
        click.echo(f"random_ids={random_ids}")

    runner = CliRunner()
    result = runner.invoke(cmd, ["--uuid", "stable"])
    assert result.exit_code == 0
    assert "random_ids=False" in result.stdout
    assert "warning: '--uuid'" in result.stderr


def test_flag_alias_simple_passthrough_without_transform() -> None:
    reset_deprecation_state()

    @click.command()
    @deprecated_option(["--old-name"], canonical="--new-name")
    @click.option("--new-name", default="")
    def cmd(new_name: str) -> None:
        click.echo(f"new_name={new_name}")

    runner = CliRunner()
    result = runner.invoke(cmd, ["--old-name", "hello"])
    assert result.exit_code == 0
    assert "new_name=hello" in result.stdout
    assert "warning: '--old-name' is deprecated" in result.stderr


# --- multiple=True repeatable option --------------------------------------


def _make_multiple_cmd() -> click.Command:
    """Build a command with a deprecated repeatable option."""

    @click.command()
    @deprecated_option(["--folder"], canonical="--include-folder", multiple=True)
    @click.option("--include-folder", multiple=True, default=())
    def cmd(include_folder: tuple[str, ...]) -> None:
        click.echo(f"include_folder={include_folder!r}")

    return cmd


def test_flag_alias_multiple_canonical_only_is_silent() -> None:
    reset_deprecation_state()
    runner = CliRunner()
    result = runner.invoke(
        _make_multiple_cmd(),
        ["--include-folder", "a", "--include-folder", "b"],
    )
    assert result.exit_code == 0
    assert "include_folder=('a', 'b')" in result.stdout
    assert "deprecated" not in result.stderr


def test_flag_alias_multiple_neither_is_silent() -> None:
    reset_deprecation_state()
    runner = CliRunner()
    result = runner.invoke(_make_multiple_cmd(), [])
    assert result.exit_code == 0
    assert "include_folder=()" in result.stdout
    assert "deprecated" not in result.stderr


def test_flag_alias_multiple_deprecated_forwards_values() -> None:
    reset_deprecation_state()
    runner = CliRunner()
    result = runner.invoke(
        _make_multiple_cmd(),
        ["--folder", "a", "--folder", "b"],
    )
    assert result.exit_code == 0
    assert "include_folder=('a', 'b')" in result.stdout
    assert "warning: '--folder' is deprecated; use '--include-folder' instead." in result.stderr


def test_flag_alias_multiple_warns_only_once_for_repeats() -> None:
    reset_deprecation_state()
    runner = CliRunner()
    result = runner.invoke(
        _make_multiple_cmd(),
        ["--folder", "a", "--folder", "b", "--folder", "c"],
    )
    assert result.exit_code == 0
    assert result.stderr.count("warning: '--folder' is deprecated") == 1


# --- dedupe ---------------------------------------------------------------


def test_warning_emitted_once_per_invocation_for_command_alias() -> None:
    reset_deprecation_state()
    cli = _make_canonical_group()
    deprecated_command_alias(cli, alias="import", canonical="add")
    runner = CliRunner()
    result = runner.invoke(cli, ["import", "book.epub"])
    assert result.exit_code == 0
    assert result.stderr.count("warning: 'import' is deprecated") == 1


def test_warning_emitted_once_per_invocation_for_flag_alias() -> None:
    reset_deprecation_state()

    @click.command()
    @deprecated_option(["--old-name"], canonical="--new-name")
    @click.option("--new-name", default="")
    def cmd(new_name: str) -> None:
        click.echo(f"new_name={new_name}")

    runner = CliRunner()
    result = runner.invoke(cmd, ["--old-name", "hello"])
    assert result.exit_code == 0
    assert result.stderr.count("warning: '--old-name' is deprecated") == 1


def test_separate_invocations_each_warn() -> None:
    # Each fresh CLI invocation in production starts a new process, so the
    # dedupe state must be resettable. Validate by resetting between runs.
    cli = _make_canonical_group()
    deprecated_command_alias(cli, alias="import", canonical="add")
    runner = CliRunner()

    reset_deprecation_state()
    first = runner.invoke(cli, ["import", "book.epub"])
    reset_deprecation_state()
    second = runner.invoke(cli, ["import", "book.epub"])

    assert "warning: 'import' is deprecated" in first.stderr
    assert "warning: 'import' is deprecated" in second.stderr
