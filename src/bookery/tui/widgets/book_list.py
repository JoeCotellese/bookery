# ABOUTME: BookList widget for the TUI left pane.
# ABOUTME: Displays a sorted DataTable of books with a row count footer.

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Static

from bookery.core.pathformat import derive_author_sort
from bookery.db.mapping import BookRecord


def format_row_label(record: BookRecord) -> str:
    """Format a BookRecord as 'Author Last, First \u2014 Title' for display."""
    author_sort = derive_author_sort(record.metadata)
    if author_sort == "Unknown":
        author_sort = "Unknown Author"

    title = record.metadata.title if record.metadata.title else "(Untitled)"

    return f"{author_sort} \u2014 {title}"


def author_sort_key(record: BookRecord) -> tuple[int, str]:
    """Return a sort key that orders known authors first, case-insensitive.

    Unknown authors sort last via the leading tuple element:
    (0, "calvino, italo") < (1, "unknown").
    """
    author_sort = derive_author_sort(record.metadata)
    if author_sort == "Unknown":
        return (1, "unknown")
    return (0, author_sort.lower())


class BookList(Widget):
    """A widget composing a DataTable of books and a row count label."""

    can_focus_children = True

    def compose(self) -> ComposeResult:
        yield DataTable(id="book-table")
        yield Static("0 books", id="row-count")

    def on_mount(self) -> None:
        table = self.query_one("#book-table", DataTable)
        table.add_column("Library", key="library")
        table.cursor_type = "row"

    def load(self, records: list[BookRecord]) -> None:
        """Sort records by author, populate the DataTable, and update count."""
        sorted_records = sorted(records, key=author_sort_key)

        table = self.query_one("#book-table", DataTable)
        table.clear()

        for record in sorted_records:
            label = format_row_label(record)
            table.add_row(label, key=str(record.id))

        count = len(sorted_records)
        noun = "book" if count == 1 else "books"
        self.query_one("#row-count", Static).update(f"{count} {noun}")
