# ABOUTME: Unit tests for the CandidateTable widget.
# ABOUTME: Verifies candidate rendering, confidence display, and row ordering.

import pytest

from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.types import BookMetadata
from bookery.tui.widgets.candidate_table import CandidateTable, confidence_tier


def _make_candidate(
    title: str = "Test Book",
    authors: list[str] | None = None,
    confidence: float = 0.9,
    source: str = "openlibrary",
    isbn: str | None = None,
    language: str | None = None,
) -> MetadataCandidate:
    """Create a test MetadataCandidate."""
    return MetadataCandidate(
        metadata=BookMetadata(
            title=title,
            authors=authors or ["Test Author"],
            isbn=isbn,
            language=language,
        ),
        confidence=confidence,
        source=source,
        source_id="test-id",
    )


class TestConfidenceTier:
    """Tests for the confidence_tier helper."""

    def test_high_confidence(self) -> None:
        assert confidence_tier(0.85) == "HIGH"

    def test_medium_confidence(self) -> None:
        assert confidence_tier(0.65) == "MED"

    def test_low_confidence(self) -> None:
        assert confidence_tier(0.3) == "LOW"

    def test_boundary_high(self) -> None:
        assert confidence_tier(0.8) == "HIGH"

    def test_boundary_medium(self) -> None:
        assert confidence_tier(0.5) == "MED"


@pytest.mark.asyncio
class TestCandidateTableWidget:
    """Tests for the CandidateTable Textual widget."""

    async def test_renders_candidates_with_correct_columns(self) -> None:
        """CandidateTable shows all expected columns."""
        from textual.app import App, ComposeResult
        from textual.widgets import DataTable

        candidates = [_make_candidate()]

        class TestApp(App):
            def compose(self) -> ComposeResult:
                yield CandidateTable(id="ct")

            def on_mount(self) -> None:
                self.query_one(CandidateTable).load(candidates)

        app = TestApp()
        async with app.run_test():
            table = app.query_one("#candidate-table", DataTable)
            assert table.row_count == 1

    async def test_confidence_shown_as_percentage(self) -> None:
        """Confidence 0.85 renders as '85% HIGH'."""
        from textual.app import App, ComposeResult
        from textual.widgets import DataTable

        candidates = [_make_candidate(confidence=0.85)]

        class TestApp(App):
            def compose(self) -> ComposeResult:
                yield CandidateTable(id="ct")

            def on_mount(self) -> None:
                self.query_one(CandidateTable).load(candidates)

        app = TestApp()
        async with app.run_test():
            table = app.query_one("#candidate-table", DataTable)
            row = table.get_row_at(0)
            row_text = " ".join(str(cell) for cell in row)
            assert "85%" in row_text
            assert "HIGH" in row_text

    async def test_shows_title_and_author(self) -> None:
        """Candidate title and author are visible in the table."""
        from textual.app import App, ComposeResult
        from textual.widgets import DataTable

        candidates = [_make_candidate(title="Dune", authors=["Frank Herbert"])]

        class TestApp(App):
            def compose(self) -> ComposeResult:
                yield CandidateTable(id="ct")

            def on_mount(self) -> None:
                self.query_one(CandidateTable).load(candidates)

        app = TestApp()
        async with app.run_test():
            table = app.query_one("#candidate-table", DataTable)
            row = table.get_row_at(0)
            row_text = " ".join(str(cell) for cell in row)
            assert "Dune" in row_text
            assert "Frank Herbert" in row_text

    async def test_empty_candidates_shows_no_rows(self) -> None:
        """Empty candidate list produces zero table rows."""
        from textual.app import App, ComposeResult
        from textual.widgets import DataTable

        class TestApp(App):
            def compose(self) -> ComposeResult:
                yield CandidateTable(id="ct")

            def on_mount(self) -> None:
                self.query_one(CandidateTable).load([])

        app = TestApp()
        async with app.run_test():
            table = app.query_one("#candidate-table", DataTable)
            assert table.row_count == 0

    async def test_multiple_candidates_ordered_by_index(self) -> None:
        """Multiple candidates render in the order they are provided."""
        from textual.app import App, ComposeResult
        from textual.widgets import DataTable

        candidates = [
            _make_candidate(title="Best Match", confidence=0.95),
            _make_candidate(title="Okay Match", confidence=0.60),
        ]

        class TestApp(App):
            def compose(self) -> ComposeResult:
                yield CandidateTable(id="ct")

            def on_mount(self) -> None:
                self.query_one(CandidateTable).load(candidates)

        app = TestApp()
        async with app.run_test():
            table = app.query_one("#candidate-table", DataTable)
            assert table.row_count == 2
            first_row = " ".join(str(cell) for cell in table.get_row_at(0))
            assert "Best Match" in first_row
