# ABOUTME: Unit tests for the MetadataDiff widget.
# ABOUTME: Verifies compact/full modes, change markers, and data loss warnings.

import pytest

from bookery.metadata.types import BookMetadata
from bookery.tui.widgets.metadata_diff import FieldDiff, MetadataDiff, compute_field_diffs


class TestComputeFieldDiffs:
    """Tests for the compute_field_diffs helper."""

    def test_identical_metadata_all_unchanged(self) -> None:
        """Identical current and proposed produces all 'unchanged' diffs."""
        meta = BookMetadata(title="Test", authors=["Author"], isbn="123")
        diffs = compute_field_diffs(meta, meta)
        assert all(d.change == "unchanged" for d in diffs)

    def test_added_field_detected(self) -> None:
        """A field going from None to a value is marked as 'added'."""
        current = BookMetadata(title="Test")
        proposed = BookMetadata(title="Test", isbn="978-0-123456-47-2")
        diffs = compute_field_diffs(current, proposed)

        isbn_diff = next(d for d in diffs if d.field == "ISBN")
        assert isbn_diff.change == "added"
        assert isbn_diff.proposed == "978-0-123456-47-2"

    def test_changed_field_detected(self) -> None:
        """A field with different values is marked as 'changed'."""
        current = BookMetadata(title="Old Title")
        proposed = BookMetadata(title="New Title")
        diffs = compute_field_diffs(current, proposed)

        title_diff = next(d for d in diffs if d.field == "Title")
        assert title_diff.change == "changed"
        assert title_diff.current == "Old Title"
        assert title_diff.proposed == "New Title"

    def test_removed_field_detected(self) -> None:
        """A field going from a value to None is marked as 'removed'."""
        current = BookMetadata(title="Test", publisher="Einaudi")
        proposed = BookMetadata(title="Test", publisher=None)
        diffs = compute_field_diffs(current, proposed)

        pub_diff = next(d for d in diffs if d.field == "Publisher")
        assert pub_diff.change == "removed"

    def test_authors_compared_as_string(self) -> None:
        """Authors lists are compared as joined strings."""
        current = BookMetadata(title="Test", authors=["Author A"])
        proposed = BookMetadata(title="Test", authors=["Author B"])
        diffs = compute_field_diffs(current, proposed)

        author_diff = next(d for d in diffs if d.field == "Authors")
        assert author_diff.change == "changed"

    def test_subjects_compared_as_string(self) -> None:
        """Subjects lists are compared as joined strings."""
        current = BookMetadata(title="Test", subjects=["Fiction"])
        proposed = BookMetadata(title="Test", subjects=["Fiction", "History"])
        diffs = compute_field_diffs(current, proposed)

        subj_diff = next(d for d in diffs if d.field == "Subjects")
        assert subj_diff.change == "changed"

    def test_series_with_index(self) -> None:
        """Series field includes index when present."""
        current = BookMetadata(title="Test")
        proposed = BookMetadata(title="Test", series="Cycle", series_index=3.0)
        diffs = compute_field_diffs(current, proposed)

        series_diff = next(d for d in diffs if d.field == "Series")
        assert series_diff.change == "added"
        assert "#3" in series_diff.proposed

    def test_all_diffed_fields_present(self) -> None:
        """All expected fields are present in the diff output."""
        meta = BookMetadata(title="Test")
        diffs = compute_field_diffs(meta, meta)
        field_names = {d.field for d in diffs}
        expected = {"Title", "Authors", "Publisher", "ISBN", "Language",
                    "Description", "Series", "Subjects"}
        assert expected == field_names


class TestFieldDiffMarker:
    """Tests for FieldDiff.marker property."""

    def test_added_marker(self) -> None:
        diff = FieldDiff(field="ISBN", current="", proposed="123", change="added")
        assert diff.marker == "[+]"

    def test_changed_marker(self) -> None:
        diff = FieldDiff(field="Title", current="A", proposed="B", change="changed")
        assert diff.marker == "[~]"

    def test_removed_marker(self) -> None:
        diff = FieldDiff(field="ISBN", current="123", proposed="", change="removed")
        assert diff.marker == "[-]"

    def test_unchanged_marker(self) -> None:
        diff = FieldDiff(field="Title", current="A", proposed="A", change="unchanged")
        assert diff.marker == ""


@pytest.mark.asyncio
class TestMetadataDiffWidget:
    """Tests for the MetadataDiff Textual widget."""

    async def test_compact_mode_hides_unchanged_fields(self) -> None:
        """In compact mode, unchanged fields are not rendered."""
        from textual.app import App, ComposeResult

        current = BookMetadata(title="Same Title", isbn="123")
        proposed = BookMetadata(title="Same Title", isbn="456")

        class TestApp(App):
            def compose(self) -> ComposeResult:
                yield MetadataDiff(current, proposed, mode="compact")

        app = TestApp()
        async with app.run_test():
            widget = app.query_one(MetadataDiff)
            rendered = str(widget.render())
            # ISBN changed, should be visible
            assert "ISBN" in rendered
            # Title unchanged, should not be in compact mode
            assert "Same Title" not in rendered or rendered.count("Same Title") == 0

    async def test_full_mode_shows_all_fields(self) -> None:
        """In full mode, all fields are rendered including unchanged ones."""
        from textual.app import App, ComposeResult

        current = BookMetadata(title="Same Title", isbn="123")
        proposed = BookMetadata(title="Same Title", isbn="456")

        class TestApp(App):
            def compose(self) -> ComposeResult:
                yield MetadataDiff(current, proposed, mode="full")

        app = TestApp()
        async with app.run_test():
            widget = app.query_one(MetadataDiff)
            rendered = str(widget.render())
            assert "Title" in rendered
            assert "ISBN" in rendered

    async def test_data_loss_warning_on_removed_field(self) -> None:
        """Removed fields show a data loss warning marker in full mode."""
        from textual.app import App, ComposeResult

        current = BookMetadata(title="Test", publisher="Einaudi")
        proposed = BookMetadata(title="Test", publisher=None)

        class TestApp(App):
            def compose(self) -> ComposeResult:
                yield MetadataDiff(current, proposed, mode="full")

        app = TestApp()
        async with app.run_test():
            widget = app.query_one(MetadataDiff)
            rendered = str(widget.render())
            assert "[-]" in rendered

    async def test_update_diff_changes_content(self) -> None:
        """update_diff() changes the displayed content."""
        from textual.app import App, ComposeResult

        current1 = BookMetadata(title="First")
        proposed1 = BookMetadata(title="First Changed")
        current2 = BookMetadata(title="Second")
        proposed2 = BookMetadata(title="Second Changed")

        class TestApp(App):
            def compose(self) -> ComposeResult:
                yield MetadataDiff(current1, proposed1, mode="full")

        app = TestApp()
        async with app.run_test():
            widget = app.query_one(MetadataDiff)
            widget.update_diff(current2, proposed2)
            rendered = str(widget.render())
            assert "Second" in rendered
