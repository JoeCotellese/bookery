# ABOUTME: Candidate selection screen with split pane layout.
# ABOUTME: Shows ranked candidates on top and a live diff preview below.

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Static

from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.types import BookMetadata
from bookery.tui.widgets.candidate_table import CandidateTable
from bookery.tui.widgets.metadata_diff import MetadataDiff


class CandidateSelectScreen(Screen[MetadataCandidate | None]):
    """Split-pane screen for selecting a metadata candidate.

    Top pane: ranked candidate table.
    Bottom pane: diff preview of highlighted candidate vs current metadata.

    Dismisses with the selected MetadataCandidate, or None on cancel.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel"),
        Binding("m", "manual_search", "Manual search"),
    ]

    def __init__(
        self,
        current: BookMetadata,
        candidates: list[MetadataCandidate],
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._current = current
        self._candidates = candidates

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(
                "[bold]Select a candidate[/bold]  "
                "[dim]Enter: select  m: manual search  Esc: cancel[/dim]",
                id="candidate-header",
            )
            yield CandidateTable(id="candidate-list")
            yield MetadataDiff(
                self._current,
                self._candidates[0].metadata if self._candidates else self._current,
                mode="compact",
                id="candidate-diff",
            )

    def on_mount(self) -> None:
        self.query_one(CandidateTable).load(self._candidates)
        # Focus the candidate table
        table = self.query_one("#candidate-table", DataTable)
        table.focus()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Update the diff preview when a candidate row is highlighted."""
        if event.row_key is None or event.row_key.value is None:
            return

        index = int(event.row_key.value)
        candidate_table = self.query_one(CandidateTable)
        candidate = candidate_table.get_candidate_at(index)
        if candidate is None:
            return

        self.query_one(MetadataDiff).update_diff(self._current, candidate.metadata)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle Enter on a candidate row — select and dismiss."""
        if event.row_key is None or event.row_key.value is None:
            return

        index = int(event.row_key.value)
        candidate_table = self.query_one(CandidateTable)
        candidate = candidate_table.get_candidate_at(index)
        if candidate is not None:
            self.dismiss(candidate)

    def action_cancel(self) -> None:
        """Cancel and return to the book list."""
        self.dismiss(None)

    def action_manual_search(self) -> None:
        """Open the manual search modal."""
        from bookery.tui.screens.manual import ManualSearchModal

        self.app.push_screen(ManualSearchModal())
