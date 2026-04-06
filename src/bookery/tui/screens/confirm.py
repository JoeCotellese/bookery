# ABOUTME: Confirmation screen for metadata enrichment write-back.
# ABOUTME: Shows full field-by-field diff with accept, back, and cancel actions.

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Static

from bookery.metadata.types import BookMetadata
from bookery.tui.widgets.metadata_diff import MetadataDiff, compute_field_diffs


class ConfirmScreen(Screen[bool | None]):
    """Full field-by-field diff confirmation before writing.

    Dismisses with:
    - True: user accepts, proceed to write
    - False: user wants to go back to candidate selection
    - None: user cancels entirely
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("y", "accept", "Accept"),
        Binding("enter", "accept", "Accept"),
        Binding("b", "back", "Back"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        current: BookMetadata,
        proposed: BookMetadata,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._current = current
        self._proposed = proposed

    def compose(self) -> ComposeResult:
        diffs = compute_field_diffs(self._current, self._proposed)
        has_data_loss = any(d.change == "removed" for d in diffs)

        with Vertical():
            yield Static(
                "[bold]Confirm metadata changes[/bold]  "
                "[dim]y/Enter: accept  b: back  Esc: cancel[/dim]",
                id="confirm-header",
            )
            if has_data_loss:
                yield Static(
                    "[bold red]Warning:[/bold red] Some existing fields "
                    "will be cleared (marked [-])",
                    id="data-loss-warning",
                )
            yield MetadataDiff(
                self._current, self._proposed, mode="full", id="confirm-diff"
            )

    def action_accept(self) -> None:
        """Accept the proposed changes."""
        self.dismiss(True)

    def action_back(self) -> None:
        """Go back to candidate selection."""
        self.dismiss(False)

    def action_cancel(self) -> None:
        """Cancel the entire enrichment flow."""
        self.dismiss(None)
