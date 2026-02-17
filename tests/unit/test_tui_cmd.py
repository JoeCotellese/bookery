# ABOUTME: Unit tests for the `bookery tui` CLI command.
# ABOUTME: Verifies command registration and error handling for missing database.

from click.testing import CliRunner

from bookery.cli import cli


class TestTuiCommand:
    """Unit tests for the tui CLI command."""

    def test_tui_registered_in_cli(self) -> None:
        """The tui command appears in the CLI group."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "tui" in result.output

    def test_missing_db_shows_error(self, tmp_path) -> None:
        """When no library DB exists, show a friendly error and exit 1."""
        nonexistent_db = tmp_path / "nope" / "library.db"
        runner = CliRunner()
        result = runner.invoke(cli, ["tui", "--db", str(nonexistent_db)])
        assert result.exit_code == 1
        assert "No library found" in result.output
