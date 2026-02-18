# ABOUTME: Unit tests for the BookeryApp Textual application.
# ABOUTME: Verifies app instantiation, quit bindings, layout composition, and focus cycling.

import sqlite3

import pytest
from textual.binding import Binding

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
        binding_keys = [
            b.key if isinstance(b, Binding) else b[0] for b in app.BINDINGS
        ]
        assert "q" in binding_keys

    def test_title_is_bookery(self, catalog: LibraryCatalog) -> None:
        """App TITLE is 'Bookery'."""
        app = BookeryApp(catalog=catalog)
        assert app.TITLE == "Bookery"

    def test_subtitle_contains_version(self, catalog: LibraryCatalog) -> None:
        """App SUB_TITLE contains the package version."""
        from bookery import __version__

        app = BookeryApp(catalog=catalog)
        assert app.SUB_TITLE is not None
        assert __version__ in app.SUB_TITLE

    @pytest.mark.asyncio
    async def test_launches_and_exits_cleanly(self, catalog: LibraryCatalog) -> None:
        """App launches in headless mode and exits cleanly."""
        app = BookeryApp(catalog=catalog)
        async with app.run_test() as pilot:
            await pilot.press("q")

    @pytest.mark.asyncio
    async def test_compose_yields_header(self, catalog: LibraryCatalog) -> None:
        """compose() yields a Header widget."""
        from textual.widgets import Header

        app = BookeryApp(catalog=catalog)
        async with app.run_test():
            headers = app.query(Header)
            assert len(headers) == 1

    @pytest.mark.asyncio
    async def test_compose_yields_footer(self, catalog: LibraryCatalog) -> None:
        """compose() yields a Footer widget."""
        from textual.widgets import Footer

        app = BookeryApp(catalog=catalog)
        async with app.run_test():
            footers = app.query(Footer)
            assert len(footers) == 1

    @pytest.mark.asyncio
    async def test_compose_has_book_list_pane(self, catalog: LibraryCatalog) -> None:
        """compose() includes a widget with id 'book-list'."""
        app = BookeryApp(catalog=catalog)
        async with app.run_test():
            book_list = app.query_one("#book-list")
            assert book_list is not None

    @pytest.mark.asyncio
    async def test_compose_has_book_detail_pane(
        self, catalog: LibraryCatalog
    ) -> None:
        """compose() includes a widget with id 'book-detail'."""
        app = BookeryApp(catalog=catalog)
        async with app.run_test():
            book_detail = app.query_one("#book-detail")
            assert book_detail is not None

    @pytest.mark.asyncio
    async def test_book_list_placeholder_text(
        self, catalog: LibraryCatalog
    ) -> None:
        """Left pane shows '0 books' when catalog is empty."""
        app = BookeryApp(catalog=catalog)
        async with app.run_test():
            row_count = app.query_one("#row-count")
            assert "0 books" in str(row_count.render())

    @pytest.mark.asyncio
    async def test_book_detail_placeholder_text(
        self, catalog: LibraryCatalog
    ) -> None:
        """Right pane shows placeholder text."""
        from textual.widgets import Static

        app = BookeryApp(catalog=catalog)
        async with app.run_test():
            book_detail = app.query_one("#book-detail")
            static = book_detail.query_one(Static)
            assert "Select a book" in str(static.render())

    @pytest.mark.asyncio
    async def test_two_panes_inside_horizontal(
        self, catalog: LibraryCatalog
    ) -> None:
        """Both panes are children of a Horizontal container."""
        from textual.containers import Horizontal

        app = BookeryApp(catalog=catalog)
        async with app.run_test():
            horizontal = app.query_one(Horizontal)
            children_ids = [child.id for child in horizontal.children]
            assert "book-list" in children_ids
            assert "book-detail" in children_ids

    @pytest.mark.asyncio
    async def test_tab_cycles_focus_between_panes(
        self, catalog: LibraryCatalog
    ) -> None:
        """Pressing Tab cycles focus between the book table and detail pane."""
        app = BookeryApp(catalog=catalog)
        async with app.run_test() as pilot:
            # Focus starts on the book table inside #book-list
            book_table = app.query_one("#book-table")
            book_table.focus()
            assert app.focused is not None
            assert app.focused.id == "book-table"

            # Tab should move to the detail pane
            await pilot.press("tab")
            assert app.focused is not None
            assert app.focused.id == "book-detail"

            # Tab moves to the scrollable region inside detail pane
            await pilot.press("tab")
            assert app.focused is not None
            assert app.focused.id == "detail-scroll"

            # Tab again should cycle back to the book table
            await pilot.press("tab")
            assert app.focused is not None
            assert app.focused.id == "book-table"
