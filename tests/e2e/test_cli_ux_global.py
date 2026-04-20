# ABOUTME: E2E tests for CLI UX improvements from issue #83.
# ABOUTME: Covers global --db, -y/--yes (quiet deprecation), --match/--no-match, threshold default.

from pathlib import Path

from click.testing import CliRunner

from bookery.cli import cli


class TestGlobalDbOption:
    """Top-level `bookery --db PATH <cmd>` reaches subcommands."""

    def test_global_db_reaches_ls(self, tmp_path: Path) -> None:
        db = tmp_path / "lib.db"
        runner = CliRunner()
        result = runner.invoke(cli, ["--db", str(db), "ls"])
        assert result.exit_code == 0, result.output
        # Opening a fresh DB creates it
        assert db.exists()

    def test_subcommand_db_overrides_global(self, tmp_path: Path) -> None:
        global_db = tmp_path / "global.db"
        sub_db = tmp_path / "sub.db"
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--db", str(global_db), "ls", "--db", str(sub_db)]
        )
        assert result.exit_code == 0, result.output
        assert sub_db.exists()
        assert not global_db.exists()


class TestAutoAcceptOption:
    """`-y/--yes` replaces `-q/--quiet`; quiet still works with deprecation."""

    def test_yes_flag_recognized_by_match(self, tmp_path: Path) -> None:
        runner = CliRunner()
        # No EPUBs found → early return; but option parsing must succeed.
        empty = tmp_path / "empty"
        empty.mkdir()
        result = runner.invoke(cli, ["match", str(empty), "-y"])
        assert result.exit_code == 0, result.output

    def test_quiet_flag_warns_but_still_works(self, tmp_path: Path) -> None:
        runner = CliRunner()
        empty = tmp_path / "empty"
        empty.mkdir()
        result = runner.invoke(cli, ["match", str(empty), "-q"])
        assert result.exit_code == 0, result.output
        assert "deprecated" in result.output.lower()

    def test_yes_flag_on_rematch(self, tmp_path: Path) -> None:
        db = tmp_path / "lib.db"
        runner = CliRunner()
        # No books → early return; option parsing is what matters here.
        result = runner.invoke(cli, ["rematch", "--all", "--db", str(db), "-y"])
        assert result.exit_code == 0, result.output


class TestDbFallback:
    """Precedence: subcommand --db > top-level --db > DEFAULT_DB_PATH."""

    def test_no_db_flag_uses_default_path(self) -> None:
        from bookery.cli.options import resolve_db_path
        from bookery.db.connection import DEFAULT_DB_PATH

        # No Click context active, no flag → fall through to DEFAULT_DB_PATH.
        assert resolve_db_path(None) == DEFAULT_DB_PATH


class TestQuietStillAutoAccepts:
    """Deprecated -q must still set auto_accept, not merely warn."""

    def test_quiet_routes_to_auto_accept_variable(self) -> None:
        # Invoke `add --help` with -q mixed in would error (conflict).
        # Instead check at the callback level: two options, same dest.
        from bookery.cli.options import auto_accept_option

        @auto_accept_option
        def cb(auto_accept: bool) -> None:
            _ = auto_accept

        # Click stores both -y and -q into the same `auto_accept` param name.
        params = [p for p in cb.__click_params__]  # type: ignore[attr-defined]
        names = [p.name for p in params]
        assert names.count("auto_accept") == 2


class TestMatchToggle:
    """Commands expose a uniform --match/--no-match toggle."""

    def test_add_help_shows_match_toggle(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["add", "--help"])
        assert "--match / --no-match" in result.output

    def test_convert_help_shows_match_toggle(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["convert", "--help"])
        assert "--match / --no-match" in result.output

    def test_import_help_shows_match_toggle(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["import", "--help"])
        assert "--match / --no-match" in result.output


class TestThresholdDefaultFromConfig:
    """-t/--threshold default is sourced from [matching].auto_accept_threshold."""

    def test_rematch_help_references_config(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["rematch", "--help"])
        assert "matching" in result.output.lower() or "config" in result.output.lower()

    def test_threshold_default_uses_config_value(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        cfg_dir = tmp_path / ".bookery"
        cfg_dir.mkdir()
        (cfg_dir / "config.toml").write_text(
            f'library_root = "{tmp_path / ".library"}"\n'
            "[matching]\n"
            "auto_accept_threshold = 0.73\n"
        )
        # Reload path — the help text doesn't show the numeric default,
        # but the callback resolves at invocation time. Exercise via config accessor.
        from bookery.core.config import get_matching_config

        assert get_matching_config().auto_accept_threshold == 0.73
