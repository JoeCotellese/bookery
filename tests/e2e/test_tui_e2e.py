# ABOUTME: End-to-end tests for the `bookery tui` command.
# ABOUTME: Verifies --help output, missing DB error, headless app launch, and two-pane layout.

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from bookery.cli import cli
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata
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

    @pytest.mark.asyncio
    async def test_empty_catalog_shows_zero_books(self, tmp_path) -> None:
        """An empty catalog shows '0 books' in the row count."""
        db_path = tmp_path / "library.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)

        app = BookeryApp(catalog=catalog)
        async with app.run_test() as pilot:
            label = app.query_one("#row-count")
            assert "0 books" in str(label.render())
            await pilot.press("q")

        conn.close()

    @pytest.mark.asyncio
    async def test_populated_catalog_renders_book_list(self, tmp_path) -> None:
        """A catalog with books renders them in the DataTable sorted by author."""
        db_path = tmp_path / "library.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)

        catalog.add_book(
            BookMetadata(title="The Name of the Rose", authors=["Umberto Eco"],
                         source_path=Path("/books/rose.epub")),
            file_hash="hash1",
        )
        catalog.add_book(
            BookMetadata(title="If on a winter's night a traveler",
                         authors=["Italo Calvino"],
                         source_path=Path("/books/winter.epub")),
            file_hash="hash2",
        )

        app = BookeryApp(catalog=catalog)
        async with app.run_test() as pilot:
            table = app.query_one("#book-table")
            assert table.row_count == 2

            # Calvino sorts before Eco
            first_row = table.get_row_at(0)
            assert "Calvino" in str(first_row[0])

            label = app.query_one("#row-count")
            assert "2 books" in str(label.render())

            await pilot.press("q")

        conn.close()

    @pytest.mark.asyncio
    async def test_select_book_shows_detail(self, tmp_path) -> None:
        """Full flow: launch app, highlight row, detail pane shows metadata."""
        db_path = tmp_path / "library.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)

        catalog.add_book(
            BookMetadata(
                title="If on a winter's night a traveler",
                authors=["Italo Calvino"],
                publisher="Einaudi",
                language="it",
                description="<p>A novel about reading novels.</p>",
                source_path=Path("/books/winter.epub"),
            ),
            file_hash="hash_winter",
        )
        catalog.add_book(
            BookMetadata(
                title="The Name of the Rose",
                authors=["Umberto Eco"],
                isbn="978-0-15-144647-6",
                series="Medieval Mysteries",
                series_index=1.0,
                source_path=Path("/books/rose.epub"),
            ),
            file_hash="hash_rose",
        )

        app = BookeryApp(catalog=catalog)
        async with app.run_test() as pilot:
            await pilot.pause()

            # Focus the table; cursor starts at row 0 (Calvino),
            # pressing down moves to row 1 (Eco).
            table = app.query_one("#book-table")
            table.focus()
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()

            # Verify the detail pane shows Eco's book (row 1)
            header = app.query_one("#detail-header")
            header_text = str(header.render())
            assert "Rose" in header_text

            metadata = app.query_one("#detail-metadata")
            meta_text = str(metadata.render())
            assert "Eco" in meta_text
            assert "978-0-15-144647-6" in meta_text
            assert "Medieval Mysteries" in meta_text
            assert "#1" in meta_text

            # Now press up to go back to Calvino (row 0)
            await pilot.press("up")
            await pilot.pause()

            header_text = str(app.query_one("#detail-header").render())
            assert "winter" in header_text.lower()

            meta_text = str(app.query_one("#detail-metadata").render())
            assert "Calvino" in meta_text
            assert "Einaudi" in meta_text

            # Description should have HTML stripped
            desc_text = str(app.query_one("#detail-description").render())
            assert "A novel about reading novels." in desc_text
            assert "<p>" not in desc_text

            await pilot.press("q")

        conn.close()
