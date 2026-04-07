# ABOUTME: Unit tests for the `bookery serve` CLI command.
# ABOUTME: Validates command registration and error handling for missing database.

from click.testing import CliRunner

from bookery.cli import cli


class TestServeCommand:
    def test_serve_registered_in_cli(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert "serve" in result.output

    def test_serve_missing_db_shows_error(self, tmp_path):
        runner = CliRunner()
        missing_db = tmp_path / "nonexistent.db"
        result = runner.invoke(cli, ["serve", "--db", str(missing_db)])
        assert result.exit_code != 0
        assert "No library found" in result.output
