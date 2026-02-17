# ABOUTME: Unit tests for the BookList TUI widget.
# ABOUTME: Tests format_row_label(), author_sort_key(), and BookList.load() behavior.

from pathlib import Path

import pytest

from bookery.db.mapping import BookRecord
from bookery.metadata.types import BookMetadata


def _make_record(
    title: str = "The Name of the Rose",
    authors: list[str] | None = None,
    record_id: int = 1,
) -> BookRecord:
    """Helper to create a BookRecord with sensible defaults."""
    if authors is None:
        authors = ["Umberto Eco"]
    return BookRecord(
        id=record_id,
        metadata=BookMetadata(title=title, authors=authors),
        file_hash="abc123",
        source_path=Path("/books/test.epub"),
        output_path=None,
        date_added="2025-01-01T00:00:00",
        date_modified="2025-01-01T00:00:00",
    )


class TestFormatRowLabel:
    """Tests for format_row_label()."""

    def test_normal_author_and_title(self) -> None:
        """Standard author/title produces 'Last, First \u2014 Title'."""
        from bookery.tui.widgets.book_list import format_row_label

        record = _make_record(title="The Name of the Rose", authors=["Umberto Eco"])
        assert format_row_label(record) == "Eco, Umberto \u2014 The Name of the Rose"

    def test_empty_authors_list(self) -> None:
        """Empty authors list produces 'Unknown Author'."""
        from bookery.tui.widgets.book_list import format_row_label

        record = _make_record(authors=[])
        assert format_row_label(record) == "Unknown Author \u2014 The Name of the Rose"

    def test_none_title(self) -> None:
        """None-ish title (empty string) produces '(Untitled)'."""
        from bookery.tui.widgets.book_list import format_row_label

        record = _make_record(title="", authors=["Umberto Eco"])
        assert format_row_label(record) == "Eco, Umberto \u2014 (Untitled)"

    def test_single_name_author(self) -> None:
        """Single-word author name is used as-is (no inversion)."""
        from bookery.tui.widgets.book_list import format_row_label

        record = _make_record(authors=["Colette"])
        assert format_row_label(record) == "Colette \u2014 The Name of the Rose"

    def test_author_with_comma_kept_as_is(self) -> None:
        """Author already containing a comma is kept as-is."""
        from bookery.tui.widgets.book_list import format_row_label

        record = _make_record(authors=["Eco, Umberto"])
        assert format_row_label(record) == "Eco, Umberto \u2014 The Name of the Rose"

    def test_whitespace_only_author(self) -> None:
        """Whitespace-only author treated as unknown."""
        from bookery.tui.widgets.book_list import format_row_label

        record = _make_record(authors=["   "])
        assert format_row_label(record) == "Unknown Author \u2014 The Name of the Rose"


class TestAuthorSortKey:
    """Tests for author_sort_key()."""

    def test_case_insensitive(self) -> None:
        """Sort keys are case-insensitive."""
        from bookery.tui.widgets.book_list import author_sort_key

        upper = _make_record(authors=["Umberto Eco"])
        lower = _make_record(authors=["umberto eco"])
        assert author_sort_key(upper) == author_sort_key(lower)

    def test_unknown_sorts_last(self) -> None:
        """Records with unknown authors sort after known authors."""
        from bookery.tui.widgets.book_list import author_sort_key

        known = _make_record(authors=["Umberto Eco"])
        unknown = _make_record(authors=[])
        assert author_sort_key(known) < author_sort_key(unknown)

    def test_ordering_by_last_name(self) -> None:
        """Records sort by author last name."""
        from bookery.tui.widgets.book_list import author_sort_key

        eco = _make_record(authors=["Umberto Eco"])
        calvino = _make_record(authors=["Italo Calvino"])
        assert author_sort_key(calvino) < author_sort_key(eco)


class TestBookListLoad:
    """Tests for BookList.load() via Textual's async test harness."""

    @pytest.mark.asyncio
    async def test_load_populates_table(self) -> None:
        """load() populates the DataTable with sorted records."""
        from textual.app import App, ComposeResult

        from bookery.tui.widgets.book_list import BookList

        records = [
            _make_record(title="The Name of the Rose", authors=["Umberto Eco"], record_id=1),
            _make_record(title="If on a winter's night", authors=["Italo Calvino"], record_id=2),
            _make_record(title="Unknown Work", authors=[], record_id=3),
        ]

        class Harness(App):
            def compose(self) -> ComposeResult:
                yield BookList(id="book-list")

        app = Harness()
        async with app.run_test() as pilot:
            book_list = app.query_one(BookList)
            book_list.load(records)
            await pilot.pause()

            table = app.query_one("#book-table")
            assert table.row_count == 3

            # Calvino should be first, Eco second, Unknown last
            first_row = table.get_row_at(0)
            assert "Calvino" in str(first_row[0])

            last_row = table.get_row_at(2)
            assert "Unknown Author" in str(last_row[0])

    @pytest.mark.asyncio
    async def test_load_updates_row_count_label(self) -> None:
        """load() updates the row count label."""
        from textual.app import App, ComposeResult

        from bookery.tui.widgets.book_list import BookList

        records = [
            _make_record(record_id=1),
            _make_record(record_id=2),
        ]

        class Harness(App):
            def compose(self) -> ComposeResult:
                yield BookList(id="book-list")

        app = Harness()
        async with app.run_test() as pilot:
            book_list = app.query_one(BookList)
            book_list.load(records)
            await pilot.pause()

            label = app.query_one("#row-count")
            assert "2 books" in str(label.render())

    @pytest.mark.asyncio
    async def test_load_singular_count(self) -> None:
        """load() with one record shows '1 book' (singular)."""
        from textual.app import App, ComposeResult

        from bookery.tui.widgets.book_list import BookList

        class Harness(App):
            def compose(self) -> ComposeResult:
                yield BookList(id="book-list")

        app = Harness()
        async with app.run_test() as pilot:
            book_list = app.query_one(BookList)
            book_list.load([_make_record()])
            await pilot.pause()

            label = app.query_one("#row-count")
            assert "1 book" in str(label.render())

    @pytest.mark.asyncio
    async def test_load_empty(self) -> None:
        """load() with no records shows '0 books'."""
        from textual.app import App, ComposeResult

        from bookery.tui.widgets.book_list import BookList

        class Harness(App):
            def compose(self) -> ComposeResult:
                yield BookList(id="book-list")

        app = Harness()
        async with app.run_test() as pilot:
            book_list = app.query_one(BookList)
            book_list.load([])
            await pilot.pause()

            label = app.query_one("#row-count")
            assert "0 books" in str(label.render())

    @pytest.mark.asyncio
    async def test_row_keys_are_record_ids(self) -> None:
        """DataTable row keys match BookRecord.id values."""
        from textual.app import App, ComposeResult

        from bookery.tui.widgets.book_list import BookList

        records = [
            _make_record(title="Book A", authors=["Author A"], record_id=42),
        ]

        class Harness(App):
            def compose(self) -> ComposeResult:
                yield BookList(id="book-list")

        app = Harness()
        async with app.run_test() as pilot:
            book_list = app.query_one(BookList)
            book_list.load(records)
            await pilot.pause()

            table = app.query_one("#book-table")
            row_key = next(iter(table.rows.keys()))
            assert row_key.value == "42"
