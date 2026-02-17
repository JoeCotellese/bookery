# ABOUTME: End-to-end tests for the `bookery tui` command.
# ABOUTME: Verifies --help output, missing DB error, headless app launch, and two-pane layout.

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.tui.app import BookeryApp


class TestTuiE2E:
    """End-to-end tests for the tui command."""

    def test_help_shows_tui_command(self) -> None:
        """bookery tui --help shows command documentation."""
        runner = CliRunner()
        result = runner.invoke(cli, ["tui", "--help"])
        assert result.exit_code == 0
        assert "Launch the interactive terminal UI" in result.output

    def test_no_db_gives_clean_error(self, tmp_path) -> None:
        """bookery tui with no DB gives a user-friendly error, no traceback."""
        nonexistent = tmp_path / "missing" / "library.db"
        runner = CliRunner()
        result = runner.invoke(cli, ["tui", "--db", str(nonexistent)])
        assert result.exit_code == 1
        assert "No library found" in result.output
        # No Python traceback in output
        assert "Traceback" not in result.output

    def test_with_db_launches_app(self, tmp_path) -> None:
        """bookery tui with a valid DB launches the Textual app."""
        db_path = tmp_path / "library.db"
        conn = open_library(db_path)
        conn.close()

        runner = CliRunner()
        with patch("bookery.cli.commands.tui_cmd.BookeryApp") as mock_app_cls:
            mock_app_cls.return_value.run.return_value = None
            result = runner.invoke(cli, ["tui", "--db", str(db_path)])

        assert result.exit_code == 0
        # Verify the app was instantiated with a LibraryCatalog
        call_kwargs = mock_app_cls.call_args
        assert isinstance(call_kwargs.kwargs["catalog"], LibraryCatalog)

    @pytest.mark.asyncio
    async def test_app_starts_headless_and_quits(self, tmp_path) -> None:
        """The Textual app starts in headless mode and quits with 'q'."""
        db_path = tmp_path / "library.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)

        app = BookeryApp(catalog=catalog)
        async with app.run_test() as pilot:
            await pilot.press("q")

        conn.close()

    @pytest.mark.asyncio
    async def test_app_mounts_with_both_panes(self, tmp_path) -> None:
        """The Textual app mounts with both book-list and book-detail panes."""
        from textual.containers import Horizontal
        from textual.widgets import Footer, Header

        db_path = tmp_path / "library.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)

        app = BookeryApp(catalog=catalog)
        async with app.run_test() as pilot:
            # Verify full layout structure
            assert len(app.query(Header)) == 1
            assert len(app.query(Footer)) == 1
            assert len(app.query(Horizontal)) == 1

            book_list = app.query_one("#book-list")
            book_detail = app.query_one("#book-detail")
            assert book_list is not None
            assert book_detail is not None

            await pilot.press("q")

        conn.close()
