# ABOUTME: Unit tests for the BookeryApp Textual application.
# ABOUTME: Verifies app instantiation, quit bindings, and clean launch/exit.

import sqlite3

import pytest

from bookery.db.catalog import LibraryCatalog
from bookery.tui.app import BookeryApp


@pytest.fixture
def catalog() -> LibraryCatalog:
    """Create a LibraryCatalog with an in-memory database."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    from bookery.db.schema import SCHEMA_V1

    conn.executescript(SCHEMA_V1)
    return LibraryCatalog(conn)


class TestBookeryAppUnit:
    """Unit tests for BookeryApp."""

    def test_instantiates_with_catalog(self, catalog: LibraryCatalog) -> None:
        """App can be created with a LibraryCatalog instance."""
        app = BookeryApp(catalog=catalog)
        assert app.catalog is catalog

    def test_has_quit_binding(self, catalog: LibraryCatalog) -> None:
        """App declares a 'q' key binding for quitting."""
        app = BookeryApp(catalog=catalog)
        binding_keys = [b.key for b in app.BINDINGS]
        assert "q" in binding_keys

    @pytest.mark.asyncio
    async def test_launches_and_exits_cleanly(self, catalog: LibraryCatalog) -> None:
        """App launches in headless mode and exits cleanly."""
        app = BookeryApp(catalog=catalog)
        async with app.run_test() as pilot:
            await pilot.press("q")
