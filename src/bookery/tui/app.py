# ABOUTME: The main Textual application for Bookery's TUI.
# ABOUTME: Provides an interactive terminal interface for browsing the library catalog.

from pathlib import Path
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal
from textual.widgets import DataTable, Footer, Header

from bookery import __version__
from bookery.db.catalog import LibraryCatalog
from bookery.tui.widgets.book_detail import BookDetail
from bookery.tui.widgets.book_list import BookList


class BookeryApp(App):
    """Bookery's interactive terminal UI."""

    TITLE = "Bookery"
    SUB_TITLE = f"v{__version__}"

    CSS_PATH = Path("styles/app.tcss")

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, catalog: LibraryCatalog, **kwargs) -> None:
        super().__init__(**kwargs)
        self.catalog = catalog

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal():
            yield BookList(id="book-list")
            yield BookDetail(id="book-detail")
        yield Footer()

    def on_mount(self) -> None:
        records = self.catalog.list_all()
        self.query_one(BookList).load(records)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """When a row is highlighted in the book list, update the detail pane."""
        if event.row_key is None or event.row_key.value is None:
            return

        book_id = int(event.row_key.value)
        record = self.catalog.get_by_id(book_id)
        if record is None:
            return

        tags = self.catalog.get_tags_for_book(book_id)
        genres = self.catalog.get_genres_for_book(book_id)
        self.query_one(BookDetail).update_detail(record, tags, genres=genres)
