# ABOUTME: BookDetail widget for the TUI right pane.
# ABOUTME: Displays full metadata for the selected book with a scrollable description.

from html.parser import HTMLParser
from io import StringIO

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

from bookery.db.mapping import BookRecord

_PLACEHOLDER = "Select a book to view details"
_EM_DASH = "\u2014"


class _HTMLStripper(HTMLParser):
    """Strips HTML tags and decodes entities, returning plain text."""

    def __init__(self) -> None:
        super().__init__()
        self._text = StringIO()

    def handle_data(self, data: str) -> None:
        self._text.write(data)

    def get_text(self) -> str:
        return self._text.getvalue()


def strip_html(value: str | None) -> str:
    """Strip HTML tags and decode entities from a string.

    Returns empty string for None or empty input.
    """
    if not value:
        return ""
    stripper = _HTMLStripper()
    stripper.feed(value)
    return stripper.get_text()


def _format_field(label: str, value: str | None) -> str:
    """Format a single metadata field with a fixed-width label column."""
    display = value if value else _EM_DASH
    return f"{label:>11}  {display}"


class BookDetail(Widget):
    """Displays full metadata for a selected book."""

    can_focus = True

    def compose(self) -> ComposeResult:
        yield Static(_PLACEHOLDER, id="detail-header")
        yield Static("", id="detail-metadata")
        with VerticalScroll(id="detail-scroll"):
            yield Static("", id="detail-description")

    def update_detail(
        self,
        record: BookRecord,
        tags: list[str],
        *,
        genres: list[tuple[str, bool]] | None = None,
    ) -> None:
        """Populate the detail pane with a book's metadata."""
        meta = record.metadata

        # Header: bold title
        self.query_one("#detail-header", Static).update(
            f"[bold]{meta.title}[/bold]"
        )

        # Build metadata lines
        lines: list[str] = []
        lines.append(_format_field("Author", f"[dim]{meta.author}[/dim]" if meta.author else None))
        lines.append(f"{'':>11}  {'─' * 30}")
        lines.append(_format_field("Publisher", meta.publisher))
        lines.append(_format_field("ISBN", meta.isbn))
        lines.append(_format_field("Language", meta.language))

        # Series with position
        if meta.series:
            series_display = meta.series
            if meta.series_index is not None:
                series_display += f" #{int(meta.series_index)}"
            lines.append(_format_field("Series", series_display))
        else:
            lines.append(_format_field("Series", None))

        # Genre
        if genres:
            genre_strs = []
            for name, is_primary in genres:
                genre_strs.append(f"{name} *" if is_primary else name)
            lines.append(_format_field("Genre", ", ".join(genre_strs)))
        else:
            lines.append(_format_field("Genre", None))

        # Tags
        if tags:
            lines.append(_format_field("Tags", ", ".join(tags)))
        else:
            lines.append(_format_field("Tags", None))

        # Filename
        filename = record.source_path.name if record.source_path else None
        lines.append(_format_field("File", filename))

        self.query_one("#detail-metadata", Static).update("\n".join(lines))

        # Description (strip HTML, show in scrollable area)
        desc = strip_html(meta.description) if meta.description else _EM_DASH
        self.query_one("#detail-description", Static).update(desc)

    def clear_detail(self) -> None:
        """Reset to placeholder state."""
        self.query_one("#detail-header", Static).update(_PLACEHOLDER)
        self.query_one("#detail-metadata", Static).update("")
        self.query_one("#detail-description", Static).update("")
