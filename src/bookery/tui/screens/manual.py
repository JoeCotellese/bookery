# ABOUTME: Manual search modal for free-text query or Open Library URL input.
# ABOUTME: Dismisses with the search query string or None on cancel.

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Center, Middle
from textual.screen import ModalScreen
from textual.widgets import Input, Static


class ManualSearchModal(ModalScreen[str | None]):
    """Modal with a text input for manual search query or Open Library URL.

    Dismisses with the query string, or None on cancel.
    URLs (http/https) are auto-detected by the caller.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Center(), Middle():
            yield Static(
                "[bold]Manual Search[/bold]\n"
                "[dim]Enter a title, author, or Open Library URL[/dim]",
                id="manual-search-label",
            )
            yield Input(
                placeholder="Search query or URL...",
                id="manual-search-input",
            )

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in the input field."""
        query = event.value.strip()
        if query:
            self.dismiss(query)

    def action_cancel(self) -> None:
        """Cancel manual search."""
        self.dismiss(None)
