# ABOUTME: The main Textual application for Bookery's TUI.
# ABOUTME: Provides an interactive terminal interface for browsing the library catalog.

from typing import ClassVar

from textual.app import App
from textual.binding import Binding, BindingType
from textual.widgets import Static

from bookery.db.catalog import LibraryCatalog


class BookeryApp(App):
    """Bookery's interactive terminal UI."""

    TITLE = "Bookery"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, catalog: LibraryCatalog, **kwargs) -> None:
        super().__init__(**kwargs)
        self.catalog = catalog

    def compose(self):
        yield Static("Bookery")
