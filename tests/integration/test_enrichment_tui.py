# ABOUTME: Integration tests for the TUI metadata enrichment workflow.
# ABOUTME: Tests the full flow with mock provider: search, select, confirm, write.

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.types import BookMetadata
from bookery.tui.app import BookeryApp


def _make_candidate(
    title: str = "Enriched Title",
    authors: list[str] | None = None,
    confidence: float = 0.9,
) -> MetadataCandidate:
    return MetadataCandidate(
        metadata=BookMetadata(
            title=title,
            authors=authors or ["Enriched Author"],
            isbn="978-0-999999-99-9",
            language="en",
        ),
        confidence=confidence,
        source="openlibrary",
        source_id="/works/OL123W",
    )


@pytest.fixture
def db_and_catalog(tmp_path):
    """Create a DB with one book and return (conn, catalog, book_id)."""
    db_path = tmp_path / "library.db"
    conn = open_library(db_path)
    catalog = LibraryCatalog(conn)

    book_id = catalog.add_book(
        BookMetadata(
            title="The Name of the Rose",
            authors=["Umberto Eco"],
            source_path=Path("/books/rose.epub"),
        ),
        file_hash="hash1",
    )
    return conn, catalog, book_id


@pytest.fixture
def mock_provider():
    """Create a mock MetadataProvider returning one candidate."""
    provider = MagicMock()
    provider.name = "mock"
    provider.search_by_isbn.return_value = []
    provider.search_by_title_author.return_value = [_make_candidate()]
    provider.lookup_by_url.return_value = None
    return provider


@pytest.mark.asyncio
class TestEnrichmentTuiIntegration:
    """Integration tests for the enrichment TUI workflow."""

    async def test_e_key_shows_loading_then_candidates(
        self, db_and_catalog, mock_provider, tmp_path
    ) -> None:
        """Pressing 'e' triggers search and shows candidate screen."""
        conn, catalog, _book_id = db_and_catalog
        from textual.widgets import DataTable

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        app = BookeryApp(
            catalog=catalog,
            output_dir=output_dir,
            provider=mock_provider,
        )

        try:
            async with app.run_test() as pilot:
                await pilot.pause()

                # Focus the book table
                table = app.query_one("#book-table", DataTable)
                table.focus()
                await pilot.pause()

                # Press 'e' to start enrichment
                await pilot.press("e")
                await pilot.pause()

                # Loading overlay should appear briefly, then candidate screen
                # Give the worker time to complete
                for _ in range(20):
                    await pilot.pause()
                    if app.screen.__class__.__name__ == "CandidateSelectScreen":
                        break

                assert app.screen.__class__.__name__ == "CandidateSelectScreen"

                # Verify candidates are loaded
                from bookery.tui.widgets.candidate_table import CandidateTable
                screen = app.screen
                ct = screen.query_one(CandidateTable)
                assert len(ct.candidates) == 1

                await pilot.press("escape")
                await pilot.pause()
                await pilot.press("q")
        finally:
            conn.close()

    async def test_e_on_enriched_book_shows_reenrich_modal(
        self, db_and_catalog, mock_provider, tmp_path
    ) -> None:
        """Pressing 'e' on an already-enriched book shows re-enrich confirmation."""
        conn, catalog, book_id = db_and_catalog
        from textual.widgets import DataTable

        # Mark the book as enriched
        catalog.set_output_path(book_id, Path("/output/rose.epub"))

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        app = BookeryApp(
            catalog=catalog,
            output_dir=output_dir,
            provider=mock_provider,
        )

        try:
            async with app.run_test() as pilot:
                await pilot.pause()

                table = app.query_one("#book-table", DataTable)
                table.focus()
                await pilot.pause()

                await pilot.press("e")
                await pilot.pause()

                # Re-enrich modal should appear
                assert app.screen.__class__.__name__ == "ReEnrichConfirmModal"

                # Cancel
                await pilot.press("escape")
                await pilot.pause()
                await pilot.press("q")
        finally:
            conn.close()

    async def test_full_enrich_flow_with_mock_provider(
        self, db_and_catalog, mock_provider, tmp_path, sample_epub
    ) -> None:
        """Full flow: e -> select candidate -> confirm -> apply succeeds."""
        conn, catalog, _book_id = db_and_catalog
        from textual.widgets import DataTable

        # Re-add with real epub path for apply to work
        catalog.delete_book(_book_id)
        book_id = catalog.add_book(
            BookMetadata(
                title="The Name of the Rose",
                authors=["Umberto Eco"],
                source_path=sample_epub,
            ),
            file_hash="hash_real",
        )

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

                # Focus and press 'e'
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

                # Select the candidate (Enter)
                screen = app.screen
                ct_table = screen.query_one("#candidate-table", DataTable)
                ct_table.focus()
                await pilot.pause()
                await pilot.press("enter")

                # Wait for confirm screen
                for _ in range(10):
                    await pilot.pause()
                    if app.screen.__class__.__name__ == "ConfirmScreen":
                        break

                assert app.screen.__class__.__name__ == "ConfirmScreen"

                # Accept (y)
                await pilot.press("y")

                # Wait for apply to complete
                for _ in range(30):
                    await pilot.pause()
                    if app.screen.__class__.__name__ != "LoadingOverlay":
                        break

                # Should be back at the main screen
                await pilot.pause()

                # Verify the catalog was updated
                updated = catalog.get_by_id(book_id)
                assert updated is not None
                assert updated.output_path is not None

                await pilot.press("q")
        finally:
            conn.close()
