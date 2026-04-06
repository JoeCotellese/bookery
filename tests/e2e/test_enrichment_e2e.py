# ABOUTME: End-to-end tests for TUI metadata enrichment.
# ABOUTME: Tests the complete enrichment workflow in a headless Textual app.

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.types import BookMetadata
from bookery.tui.app import BookeryApp


def _make_candidate(
    title: str = "The Name of the Rose",
    authors: list[str] | None = None,
    confidence: float = 0.95,
) -> MetadataCandidate:
    return MetadataCandidate(
        metadata=BookMetadata(
            title=title,
            authors=authors or ["Umberto Eco"],
            isbn="978-0-15-144647-6",
            language="en",
            publisher="Harcourt",
        ),
        confidence=confidence,
        source="openlibrary",
        source_id="/works/OL123W",
    )


@pytest.mark.asyncio
class TestEnrichmentE2E:
    """End-to-end tests for the enrichment feature."""

    async def test_enrichment_badge_appears_after_apply(
        self, tmp_path, sample_epub
    ) -> None:
        """After enrichment, the book list row shows a checkmark badge."""
        from textual.widgets import DataTable

        db_path = tmp_path / "library.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)

        catalog.add_book(
            BookMetadata(
                title="The Name of the Rose",
                authors=["Umberto Eco"],
                source_path=sample_epub,
            ),
            file_hash="hash1",
        )

        mock_provider = MagicMock()
        mock_provider.name = "mock"
        mock_provider.search_by_isbn.return_value = []
        mock_provider.search_by_title_author.return_value = [_make_candidate()]

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        app = BookeryApp(
            catalog=catalog,
            output_dir=output_dir,
            provider=mock_provider,
        )

        try:
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()

                # Focus table and check initial state (no checkmark)
                table = app.query_one("#book-table", DataTable)
                table.focus()
                await pilot.pause()

                initial_row = str(table.get_row_at(0)[0])
                assert "\u2713" not in initial_row

                # Start enrichment
                await pilot.press("e")

                # Wait for candidate screen
                for _ in range(20):
                    await pilot.pause()
                    if app.screen.__class__.__name__ == "CandidateSelectScreen":
                        break

                # Select and confirm
                screen = app.screen
                ct_table = screen.query_one("#candidate-table", DataTable)
                ct_table.focus()
                await pilot.pause()
                await pilot.press("enter")

                for _ in range(10):
                    await pilot.pause()
                    if app.screen.__class__.__name__ == "ConfirmScreen":
                        break

                await pilot.press("y")

                # Wait for apply to complete
                for _ in range(30):
                    await pilot.pause()

                # Check the row now has a checkmark
                table = app.query_one("#book-table", DataTable)
                if table.row_count > 0:
                    updated_row = str(table.get_row_at(0)[0])
                    assert "\u2713" in updated_row

                await pilot.press("q")
        finally:
            conn.close()

    async def test_escape_cancels_enrichment_at_candidate_screen(
        self, tmp_path
    ) -> None:
        """Pressing Escape at candidate screen returns to main screen."""
        db_path = tmp_path / "library.db"
        conn = open_library(db_path)
        catalog = LibraryCatalog(conn)

        catalog.add_book(
            BookMetadata(
                title="Test Book",
                authors=["Test Author"],
                source_path=Path("/books/test.epub"),
            ),
            file_hash="hash1",
        )

        mock_provider = MagicMock()
        mock_provider.name = "mock"
        mock_provider.search_by_isbn.return_value = []
        mock_provider.search_by_title_author.return_value = [_make_candidate()]

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        app = BookeryApp(
            catalog=catalog,
            output_dir=output_dir,
            provider=mock_provider,
        )

        try:
            async with app.run_test() as pilot:
                from textual.widgets import DataTable
                await pilot.pause()

                table = app.query_one("#book-table", DataTable)
                table.focus()
                await pilot.pause()

                await pilot.press("e")

                # Wait for candidate screen
                for _ in range(20):
                    await pilot.pause()
                    if app.screen.__class__.__name__ == "CandidateSelectScreen":
                        break

                assert app.screen.__class__.__name__ == "CandidateSelectScreen"

                # Cancel
                await pilot.press("escape")
                await pilot.pause()

                # Back to default screen
                assert app.screen.__class__.__name__ != "CandidateSelectScreen"

                await pilot.press("q")
        finally:
            conn.close()
