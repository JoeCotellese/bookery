# ABOUTME: Unit tests for the CandidateSelectScreen.
# ABOUTME: Verifies split-pane layout, candidate selection, and dismiss behavior.

import pytest

from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.types import BookMetadata
from bookery.tui.screens.candidates import CandidateSelectScreen
from bookery.tui.widgets.candidate_table import CandidateTable
from bookery.tui.widgets.metadata_diff import MetadataDiff


def _make_candidate(
    title: str = "Test Book",
    confidence: float = 0.9,
) -> MetadataCandidate:
    return MetadataCandidate(
        metadata=BookMetadata(title=title, authors=["Test Author"]),
        confidence=confidence,
        source="openlibrary",
        source_id="test-id",
    )


@pytest.mark.asyncio
class TestCandidateSelectScreen:
    """Tests for the CandidateSelectScreen."""

    async def test_screen_has_candidate_table_and_diff(self) -> None:
        """Screen contains both CandidateTable and MetadataDiff widgets."""
        from textual.app import App

        current = BookMetadata(title="Original")
        candidates = [_make_candidate()]

        class TestApp(App):
            def on_mount(self) -> None:
                self.push_screen(
                    CandidateSelectScreen(current, candidates)
                )

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            assert len(screen.query(CandidateTable)) == 1
            assert len(screen.query(MetadataDiff)) == 1

    async def test_escape_dismisses_with_none(self) -> None:
        """Pressing Escape dismisses the screen with None."""
        from textual.app import App

        current = BookMetadata(title="Original")
        candidates = [_make_candidate()]
        result = None

        class TestApp(App):
            def on_mount(self) -> None:
                self.push_screen(
                    CandidateSelectScreen(current, candidates),
                    callback=self._on_dismiss,
                )

            def _on_dismiss(self, value: MetadataCandidate | None) -> None:
                nonlocal result
                result = value

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

        assert result is None

    async def test_enter_selects_highlighted_candidate(self) -> None:
        """Pressing Enter on a highlighted candidate dismisses with that candidate."""
        from textual.app import App
        from textual.widgets import DataTable

        current = BookMetadata(title="Original")
        candidate = _make_candidate(title="Selected Book")
        candidates = [candidate]
        result = "not_set"

        class TestApp(App):
            def on_mount(self) -> None:
                self.push_screen(
                    CandidateSelectScreen(current, candidates),
                    callback=self._on_dismiss,
                )

            def _on_dismiss(self, value: MetadataCandidate | None) -> None:
                nonlocal result
                result = value

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            # Focus the candidate table and press enter
            screen = app.screen
            table = screen.query_one("#candidate-table", DataTable)
            table.focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

        assert result is not None
        assert result != "not_set"
        assert result.metadata.title == "Selected Book"

    async def test_no_candidates_shows_empty_table(self) -> None:
        """Empty candidate list produces zero table rows."""
        from textual.app import App
        from textual.widgets import DataTable

        current = BookMetadata(title="Original")

        class TestApp(App):
            def on_mount(self) -> None:
                self.push_screen(
                    CandidateSelectScreen(current, [])
                )

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = app.screen
            table = screen.query_one("#candidate-table", DataTable)
            assert table.row_count == 0
