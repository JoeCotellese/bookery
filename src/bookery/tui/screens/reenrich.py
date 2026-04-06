# ABOUTME: Re-enrichment confirmation modal for already-enriched books.
# ABOUTME: Asks user to confirm before re-enriching a book that has an existing output.

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Center, Middle
from textual.screen import ModalScreen
from textual.widgets import Static


class ReEnrichConfirmModal(ModalScreen[bool]):
    """Confirmation dialog when a book has already been enriched.

    Dismisses with True (proceed) or False (cancel).
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("y", "confirm", "Yes"),
        Binding("n", "decline", "No"),
        Binding("escape", "decline", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Center(), Middle():
            yield Static(
                "[bold]This book has already been enriched.[/bold]\n\n"
                "Re-enriching will create a new copy.\n"
                "The previous enriched copy will not be overwritten.\n\n"
                "[dim]y: proceed  n/Esc: cancel[/dim]",
                id="reenrich-message",
            )

    def action_confirm(self) -> None:
        """Proceed with re-enrichment."""
        self.dismiss(True)

    def action_decline(self) -> None:
        """Cancel re-enrichment."""
        self.dismiss(False)
