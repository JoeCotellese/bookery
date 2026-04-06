# ABOUTME: Loading overlay modal shown during async operations.
# ABOUTME: Displays a spinner and message while metadata search or write is in progress.

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Center, Middle
from textual.screen import ModalScreen
from textual.widgets import LoadingIndicator, Static


class LoadingOverlay(ModalScreen[None]):
    """Translucent modal overlay with spinner shown during async operations."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, message: str = "Loading...", **kwargs) -> None:
        super().__init__(**kwargs)
        self._message = message

    def compose(self) -> ComposeResult:
        with Center(), Middle():
            yield LoadingIndicator()
            yield Static(self._message, id="loading-message")

    def action_cancel(self) -> None:
        """Cancel the loading operation."""
        self.dismiss(None)
