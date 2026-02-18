# ABOUTME: Integration tests for the `bookery tui` CLI command.
# ABOUTME: Tests command invocation, and selection→detail flow with a real database.

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata
from bookery.tui.app import BookeryApp


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

    @pytest.mark.asyncio
    async def test_row_highlight_updates_detail_pane(self, tmp_path) -> None:
        """Highlighting a row in the DataTable populates the detail pane."""
        db_path = tmp_path / "library.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)

        catalog.add_book(
            BookMetadata(
                title="The Name of the Rose",
                authors=["Umberto Eco"],
                publisher="Harcourt",
                isbn="978-0-15-144647-6",
                source_path=Path("/books/rose.epub"),
            ),
            file_hash="hash1",
        )

        app = BookeryApp(catalog=catalog)
        async with app.run_test() as pilot:
            # Give the app time to mount and load
            await pilot.pause()

            # The table should have one row; move cursor to highlight it
            table = app.query_one("#book-table")
            assert table.row_count == 1

            # Press down to trigger RowHighlighted on the first row
            table.focus()
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()

            # Verify detail pane updated
            header = app.query_one("#detail-header")
            rendered = str(header.render())
            assert "The Name of the Rose" in rendered

            metadata = app.query_one("#detail-metadata")
            meta_rendered = str(metadata.render())
            assert "Umberto Eco" in meta_rendered
            assert "Harcourt" in meta_rendered

            await pilot.press("q")

        conn.close()
