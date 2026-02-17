# ABOUTME: Integration tests for the `bookery tui` CLI command.
# ABOUTME: Tests command invocation with a real database file.

from unittest.mock import patch

from click.testing import CliRunner

from bookery.cli import cli
from bookery.db.connection import open_library


class TestTuiIntegration:
    """Integration tests for tui command with real DB."""

    def test_with_existing_db_does_not_crash(self, tmp_path) -> None:
        """With a real DB file, the command invokes the app without crashing."""
        db_path = tmp_path / "library.db"
        # Create the DB so it exists
        conn = open_library(db_path)
        conn.close()

        runner = CliRunner()
        # Mock BookeryApp.run() to avoid actually launching the TUI
        with patch("bookery.cli.commands.tui_cmd.BookeryApp") as mock_app_cls:
            mock_app_cls.return_value.run.return_value = None
            result = runner.invoke(cli, ["tui", "--db", str(db_path)])

        assert result.exit_code == 0
        mock_app_cls.assert_called_once()
        mock_app_cls.return_value.run.assert_called_once()
