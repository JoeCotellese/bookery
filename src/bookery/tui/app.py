# ABOUTME: The main Textual application for Bookery's TUI.
# ABOUTME: Provides an interactive terminal interface for browsing the library catalog.

from pathlib import Path
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Footer, Header, Static

from bookery import __version__
from bookery.db.catalog import LibraryCatalog


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
            with VerticalScroll(id="book-list", can_focus=True):
                yield Static("No books loaded")
            with VerticalScroll(id="book-detail", can_focus=True):
                yield Static("Select a book to view details")
        yield Footer()
