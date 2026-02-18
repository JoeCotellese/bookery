# ABOUTME: Unit tests for the BookDetail TUI widget.
# ABOUTME: Tests strip_html(), update_detail(), clear_detail(), and field rendering.

from pathlib import Path

import pytest

from bookery.db.mapping import BookRecord
from bookery.metadata.types import BookMetadata


def _make_record(
    title: str = "The Name of the Rose",
    authors: list[str] | None = None,
    record_id: int = 1,
    publisher: str | None = None,
    isbn: str | None = None,
    language: str | None = None,
    series: str | None = None,
    series_index: float | None = None,
    description: str | None = None,
) -> BookRecord:
    """Helper to create a BookRecord with sensible defaults."""
    if authors is None:
        authors = ["Umberto Eco"]
    return BookRecord(
        id=record_id,
        metadata=BookMetadata(
            title=title,
            authors=authors,
            publisher=publisher,
            isbn=isbn,
            language=language,
            series=series,
            series_index=series_index,
            description=description,
        ),
        file_hash="abc123",
        source_path=Path("/books/test.epub"),
        output_path=None,
        date_added="2025-01-01T00:00:00",
        date_modified="2025-01-01T00:00:00",
    )


class TestStripHtml:
    """Tests for strip_html()."""

    def test_plain_text_passthrough(self) -> None:
        """Plain text without HTML tags passes through unchanged."""
        from bookery.tui.widgets.book_detail import strip_html

        assert strip_html("Hello, world!") == "Hello, world!"

    def test_strips_p_tags(self) -> None:
        """Paragraph tags are stripped."""
        from bookery.tui.widgets.book_detail import strip_html

        assert strip_html("<p>Hello</p>") == "Hello"

    def test_strips_br_tags(self) -> None:
        """Break tags are stripped."""
        from bookery.tui.widgets.book_detail import strip_html

        assert strip_html("Line one<br>Line two") == "Line oneLine two"

    def test_strips_bold_tags(self) -> None:
        """Bold tags are stripped."""
        from bookery.tui.widgets.book_detail import strip_html

        assert strip_html("<b>Bold text</b>") == "Bold text"

    def test_decodes_html_entities(self) -> None:
        """HTML entities are decoded to their characters."""
        from bookery.tui.widgets.book_detail import strip_html

        assert strip_html("Tom &amp; Jerry") == "Tom & Jerry"

    def test_none_returns_empty_string(self) -> None:
        """None input returns empty string."""
        from bookery.tui.widgets.book_detail import strip_html

        assert strip_html(None) == ""

    def test_empty_string_returns_empty(self) -> None:
        """Empty string returns empty string."""
        from bookery.tui.widgets.book_detail import strip_html

        assert strip_html("") == ""


class TestBookDetailUpdateDetail:
    """Tests for BookDetail.update_detail() rendering."""

    @pytest.mark.asyncio
    async def test_title_rendered_bold(self) -> None:
        """update_detail() renders the title as bold markup."""
        from textual.app import App, ComposeResult

        from bookery.tui.widgets.book_detail import BookDetail

        record = _make_record(title="The Name of the Rose")

        class Harness(App):
            def compose(self) -> ComposeResult:
                yield BookDetail(id="book-detail")

        app = Harness()
        async with app.run_test() as pilot:
            detail = app.query_one(BookDetail)
            detail.update_detail(record, [])
            await pilot.pause()

            header = app.query_one("#detail-header")
            rendered = str(header.render())
            assert "The Name of the Rose" in rendered

    @pytest.mark.asyncio
    async def test_author_rendered(self) -> None:
        """update_detail() renders the author."""
        from textual.app import App, ComposeResult

        from bookery.tui.widgets.book_detail import BookDetail

        record = _make_record(authors=["Umberto Eco"])

        class Harness(App):
            def compose(self) -> ComposeResult:
                yield BookDetail(id="book-detail")

        app = Harness()
        async with app.run_test() as pilot:
            detail = app.query_one(BookDetail)
            detail.update_detail(record, [])
            await pilot.pause()

            metadata = app.query_one("#detail-metadata")
            rendered = str(metadata.render())
            assert "Umberto Eco" in rendered

    @pytest.mark.asyncio
    async def test_all_fields_displayed(self) -> None:
        """update_detail() renders Publisher, ISBN, Language, Series, Tags, Description."""
        from textual.app import App, ComposeResult

        from bookery.tui.widgets.book_detail import BookDetail

        record = _make_record(
            publisher="Harcourt",
            isbn="978-0-15-144647-6",
            language="en",
            series="Medieval Mysteries",
            series_index=1.0,
            description="A mystery novel set in a monastery.",
        )

        class Harness(App):
            def compose(self) -> ComposeResult:
                yield BookDetail(id="book-detail")

        app = Harness()
        async with app.run_test() as pilot:
            detail = app.query_one(BookDetail)
            detail.update_detail(record, ["fiction", "mystery"])
            await pilot.pause()

            metadata = app.query_one("#detail-metadata")
            rendered = str(metadata.render())
            assert "Harcourt" in rendered
            assert "978-0-15-144647-6" in rendered
            assert "en" in rendered
            assert "Medieval Mysteries" in rendered
            assert "#1" in rendered
            assert "fiction" in rendered
            assert "mystery" in rendered
            assert "test.epub" in rendered

            desc = app.query_one("#detail-description")
            desc_rendered = str(desc.render())
            assert "A mystery novel set in a monastery." in desc_rendered

    @pytest.mark.asyncio
    async def test_missing_fields_show_em_dash(self) -> None:
        """Missing fields display em dash."""
        from textual.app import App, ComposeResult

        from bookery.tui.widgets.book_detail import BookDetail

        record = _make_record()  # All optional fields are None

        class Harness(App):
            def compose(self) -> ComposeResult:
                yield BookDetail(id="book-detail")

        app = Harness()
        async with app.run_test() as pilot:
            detail = app.query_one(BookDetail)
            detail.update_detail(record, [])
            await pilot.pause()

            metadata = app.query_one("#detail-metadata")
            rendered = str(metadata.render())
            assert "\u2014" in rendered  # em dash for missing fields


class TestBookDetailClear:
    """Tests for BookDetail.clear_detail()."""

    @pytest.mark.asyncio
    async def test_clear_shows_placeholder(self) -> None:
        """clear_detail() restores the placeholder message."""
        from textual.app import App, ComposeResult

        from bookery.tui.widgets.book_detail import BookDetail

        record = _make_record()

        class Harness(App):
            def compose(self) -> ComposeResult:
                yield BookDetail(id="book-detail")

        app = Harness()
        async with app.run_test() as pilot:
            detail = app.query_one(BookDetail)
            detail.update_detail(record, [])
            await pilot.pause()

            detail.clear_detail()
            await pilot.pause()

            header = app.query_one("#detail-header")
            rendered = str(header.render())
            assert "Select a book to view details" in rendered

    @pytest.mark.asyncio
    async def test_initial_state_shows_placeholder(self) -> None:
        """Widget starts with placeholder text before any update."""
        from textual.app import App, ComposeResult

        from bookery.tui.widgets.book_detail import BookDetail

        class Harness(App):
            def compose(self) -> ComposeResult:
                yield BookDetail(id="book-detail")

        app = Harness()
        async with app.run_test():
            header = app.query_one("#detail-header")
            rendered = str(header.render())
            assert "Select a book to view details" in rendered


class TestBookDetailGenre:
    """Tests for genre display in BookDetail."""

    @pytest.mark.asyncio
    async def test_genre_displayed(self) -> None:
        """update_detail() renders genre when provided."""
        from textual.app import App, ComposeResult

        from bookery.tui.widgets.book_detail import BookDetail

        record = _make_record()
        genres = [("Mystery & Thriller", True), ("Literary Fiction", False)]

        class Harness(App):
            def compose(self) -> ComposeResult:
                yield BookDetail(id="book-detail")

        app = Harness()
        async with app.run_test() as pilot:
            detail = app.query_one(BookDetail)
            detail.update_detail(record, [], genres=genres)
            await pilot.pause()

            metadata = app.query_one("#detail-metadata")
            rendered = str(metadata.render())
            assert "Mystery & Thriller" in rendered
            assert "Literary Fiction" in rendered

    @pytest.mark.asyncio
    async def test_no_genre_shows_em_dash(self) -> None:
        """No genres shows em dash."""
        from textual.app import App, ComposeResult

        from bookery.tui.widgets.book_detail import BookDetail

        record = _make_record()

        class Harness(App):
            def compose(self) -> ComposeResult:
                yield BookDetail(id="book-detail")

        app = Harness()
        async with app.run_test() as pilot:
            detail = app.query_one(BookDetail)
            detail.update_detail(record, [], genres=[])
            await pilot.pause()

            metadata = app.query_one("#detail-metadata")
            rendered = str(metadata.render())
            # Genre line should show em dash when empty
            assert "\u2014" in rendered

    @pytest.mark.asyncio
    async def test_primary_genre_marked(self) -> None:
        """Primary genre is marked with an asterisk."""
        from textual.app import App, ComposeResult

        from bookery.tui.widgets.book_detail import BookDetail

        record = _make_record()
        genres = [("Science Fiction", True)]

        class Harness(App):
            def compose(self) -> ComposeResult:
                yield BookDetail(id="book-detail")

        app = Harness()
        async with app.run_test() as pilot:
            detail = app.query_one(BookDetail)
            detail.update_detail(record, [], genres=genres)
            await pilot.pause()

            metadata = app.query_one("#detail-metadata")
            rendered = str(metadata.render())
            assert "Science Fiction *" in rendered


class TestBookDetailDescription:
    """Tests for description rendering and scrollability."""

    @pytest.mark.asyncio
    async def test_description_in_scrollable_container(self) -> None:
        """Description is rendered inside a VerticalScroll container."""
        from textual.app import App, ComposeResult
        from textual.containers import VerticalScroll

        from bookery.tui.widgets.book_detail import BookDetail

        record = _make_record(description="A long description here.")

        class Harness(App):
            def compose(self) -> ComposeResult:
                yield BookDetail(id="book-detail")

        app = Harness()
        async with app.run_test() as pilot:
            detail = app.query_one(BookDetail)
            detail.update_detail(record, [])
            await pilot.pause()

            scroll = app.query_one("#detail-scroll", VerticalScroll)
            assert scroll is not None
            desc = app.query_one("#detail-description")
            assert desc is not None
