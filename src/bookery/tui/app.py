# ABOUTME: The main Textual application for Bookery's TUI.
# ABOUTME: Provides an interactive terminal interface for browsing the library catalog.

import logging
from pathlib import Path
from typing import Any, ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal
from textual.widgets import DataTable, Footer, Header
from textual.worker import Worker, WorkerState

from bookery import __version__
from bookery.core.enrichment import EnrichmentService
from bookery.core.pipeline import WriteResult
from bookery.db.catalog import LibraryCatalog
from bookery.db.mapping import BookRecord
from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.http import BookeryHttpClient
from bookery.metadata.openlibrary import OpenLibraryProvider
from bookery.metadata.provider import MetadataProvider
from bookery.metadata.types import BookMetadata
from bookery.tui.screens.candidates import CandidateSelectScreen
from bookery.tui.screens.confirm import ConfirmScreen
from bookery.tui.screens.loading import LoadingOverlay
from bookery.tui.screens.reenrich import ReEnrichConfirmModal
from bookery.tui.widgets.book_detail import BookDetail
from bookery.tui.widgets.book_list import BookList

logger = logging.getLogger(__name__)


class BookeryApp(App):
    """Bookery's interactive terminal UI."""

    TITLE = "Bookery"
    SUB_TITLE = f"v{__version__}"

    CSS_PATH: ClassVar[list[str | Path]] = [  # type: ignore[assignment]
        Path("styles/app.tcss"),
        Path("styles/enrichment.tcss"),
    ]

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "Quit"),
        Binding("e", "enrich", "Enrich"),
    ]

    def __init__(
        self,
        catalog: LibraryCatalog,
        *,
        output_dir: Path | None = None,
        provider: MetadataProvider | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.catalog = catalog
        self._output_dir = output_dir or Path("bookery-output")
        self._provider = provider
        self._enrichment_service: EnrichmentService | None = None
        self._current_record: BookRecord | None = None

    @property
    def enrichment_service(self) -> EnrichmentService:
        """Lazily create the enrichment service on first use."""
        if self._enrichment_service is None:
            provider = self._provider or self._create_provider()
            self._enrichment_service = EnrichmentService(
                provider=provider, output_dir=self._output_dir
            )
        return self._enrichment_service

    @staticmethod
    def _create_provider() -> MetadataProvider:
        """Create the default metadata provider (Open Library)."""
        http_client = BookeryHttpClient()
        return OpenLibraryProvider(http_client=http_client)

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

    def _get_selected_record(self) -> BookRecord | None:
        """Get the currently selected book record from the DataTable."""
        table = self.query_one("#book-table", DataTable)
        if table.row_count == 0:
            return None
        row_key = table.cursor_row
        if row_key < 0:
            return None
        # Get the row key value (book ID) from the cursor position
        keys = list(table.rows.keys())
        if row_key >= len(keys):
            return None
        key_value = keys[row_key].value
        if key_value is None:
            return None
        book_id = int(key_value)
        return self.catalog.get_by_id(book_id)

    # --- Enrichment flow ---

    def action_enrich(self) -> None:
        """Start the enrichment flow for the selected book."""
        record = self._get_selected_record()
        if record is None:
            return

        self._current_record = record

        # Check if already enriched
        if record.output_path is not None:
            self.push_screen(
                ReEnrichConfirmModal(),
                callback=self._on_reenrich_decision,
            )
        else:
            self._start_search(record)

    def _on_reenrich_decision(self, proceed: bool | None) -> None:
        """Handle re-enrich confirmation result."""
        if proceed and self._current_record is not None:
            self._start_search(self._current_record)

    def _start_search(self, record: BookRecord) -> None:
        """Push loading overlay and start background search."""
        self.push_screen(LoadingOverlay("Searching Open Library..."))
        self.run_worker(
            self._search_worker(record.metadata),
            name="enrichment_search",
            thread=True,
        )

    async def _search_worker(self, metadata: BookMetadata) -> list[MetadataCandidate]:
        """Run metadata search in a background thread."""
        return self.enrichment_service.search(metadata)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle worker completion for search and apply operations."""
        if event.state != WorkerState.SUCCESS:
            if event.state == WorkerState.ERROR:
                # Dismiss loading overlay on error
                if self.screen.__class__.__name__ == "LoadingOverlay":
                    self.screen.dismiss(None)
                self.notify(
                    f"Error: {event.worker.error}",
                    severity="error",
                    timeout=5,
                )
            return

        if event.worker.name == "enrichment_search":
            candidates = event.worker.result
            if candidates is not None:
                self._on_search_complete(candidates)
        elif event.worker.name == "enrichment_apply":
            result = event.worker.result
            if result is not None:
                self._on_apply_complete(result)

    def _on_search_complete(self, candidates: list[MetadataCandidate]) -> None:
        """Handle search worker completion — dismiss loading, show candidates."""
        # Dismiss loading overlay
        if self.screen.__class__.__name__ == "LoadingOverlay":
            self.screen.dismiss(None)

        if self._current_record is None:
            return

        self.push_screen(
            CandidateSelectScreen(self._current_record.metadata, candidates),
            callback=self._on_candidate_selected,
        )

    def _on_candidate_selected(self, candidate: MetadataCandidate | None) -> None:
        """Handle candidate selection — show confirm screen or cancel."""
        if candidate is None or self._current_record is None:
            return

        self.push_screen(
            ConfirmScreen(self._current_record.metadata, candidate.metadata),
            callback=lambda result: self._on_confirm_decision(result, candidate),
        )

    def _on_confirm_decision(
        self, result: bool | None, candidate: MetadataCandidate
    ) -> None:
        """Handle confirm screen result."""
        if result is True and self._current_record is not None:
            self._start_apply(self._current_record, candidate.metadata)
        elif result is False and self._current_record is not None:
            # Back to candidates — re-run search
            self._start_search(self._current_record)

    def _start_apply(self, record: BookRecord, metadata: BookMetadata) -> None:
        """Push loading overlay and start background apply."""
        self.push_screen(LoadingOverlay("Writing metadata..."))
        self.run_worker(
            self._apply_worker(record.source_path, metadata),
            name="enrichment_apply",
            thread=True,
        )

    async def _apply_worker(self, source_path: Path, metadata: BookMetadata) -> WriteResult:
        """Run metadata apply in a background thread."""
        return self.enrichment_service.apply(source_path, metadata)

    def _on_apply_complete(self, write_result: WriteResult) -> None:
        """Handle apply worker completion — update catalog, show toast."""
        # Dismiss loading overlay
        if self.screen.__class__.__name__ == "LoadingOverlay":
            self.screen.dismiss(None)

        if write_result.success and self._current_record is not None:
            # Update catalog on main thread (thread-safe)
            if write_result.path is not None:
                self.catalog.set_output_path(
                    self._current_record.id, write_result.path
                )
                self.notify(
                    f"Written to {write_result.path.name}",
                    title="Enrichment complete",
                    timeout=5,
                )
            # Refresh book list to show badge
            self._refresh_book_list()
        else:
            error_msg = write_result.error or "Unknown error"
            self.notify(
                f"Write failed: {error_msg}",
                severity="error",
                timeout=5,
            )

    def _refresh_book_list(self) -> None:
        """Reload the book list from the catalog."""
        records = self.catalog.list_all()
        self.query_one(BookList).load(records)

    # --- Manual search (via candidate screen 'm' key) ---

    def on_manual_search_modal_dismissed(self, query: str | None) -> None:
        """Handle manual search modal result."""
        if query is None or self._current_record is None:
            return

        self.push_screen(LoadingOverlay("Searching..."))
        self.run_worker(
            self._manual_search_worker(query),
            name="enrichment_search",
            thread=True,
        )

    async def _manual_search_worker(self, query: str) -> list[MetadataCandidate]:
        """Run manual search in a background thread."""
        return self.enrichment_service.search_manual(query)
