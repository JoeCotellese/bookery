# ABOUTME: Shared metadata diff widget for comparing current vs proposed metadata.
# ABOUTME: Supports compact mode (changed fields only) and full mode (all fields with markers).

from dataclasses import dataclass

from textual.widget import Widget

from bookery.metadata.types import BookMetadata

_MARKERS = {
    "added": "[+]",
    "changed": "[~]",
    "removed": "[-]",
    "unchanged": "",
}


@dataclass
class FieldDiff:
    """A single field comparison between current and proposed metadata."""

    field: str
    current: str
    proposed: str
    change: str  # "added" | "changed" | "removed" | "unchanged"

    @property
    def marker(self) -> str:
        """Change indicator symbol for display."""
        return _MARKERS.get(self.change, "")


def _field_value(value: str | None) -> str:
    """Convert a metadata field value to a display string."""
    if value is None:
        return ""
    return str(value).strip()


def _format_series(series: str | None, index: float | None) -> str:
    """Format series name with optional index."""
    if not series:
        return ""
    if index is not None:
        return f"{series} #{int(index)}"
    return series


def compute_field_diffs(
    current: BookMetadata, proposed: BookMetadata
) -> list[FieldDiff]:
    """Compare two BookMetadata instances field by field.

    Returns a list of FieldDiff objects for each comparable metadata field.
    """
    fields: list[tuple[str, str, str]] = [
        ("Title", _field_value(current.title), _field_value(proposed.title)),
        (
            "Authors",
            ", ".join(current.authors) if current.authors else "",
            ", ".join(proposed.authors) if proposed.authors else "",
        ),
        ("Publisher", _field_value(current.publisher), _field_value(proposed.publisher)),
        ("ISBN", _field_value(current.isbn), _field_value(proposed.isbn)),
        ("Language", _field_value(current.language), _field_value(proposed.language)),
        (
            "Description",
            _field_value(current.description),
            _field_value(proposed.description),
        ),
        (
            "Series",
            _format_series(current.series, current.series_index),
            _format_series(proposed.series, proposed.series_index),
        ),
        (
            "Subjects",
            ", ".join(current.subjects) if current.subjects else "",
            ", ".join(proposed.subjects) if proposed.subjects else "",
        ),
    ]

    diffs: list[FieldDiff] = []
    for field_name, cur, prop in fields:
        if cur == prop:
            change = "unchanged"
        elif not cur and prop:
            change = "added"
        elif cur and not prop:
            change = "removed"
        else:
            change = "changed"

        diffs.append(FieldDiff(field=field_name, current=cur, proposed=prop, change=change))

    return diffs


def _render_diff_lines(diffs: list[FieldDiff], mode: str) -> str:
    """Render field diffs as formatted text lines."""
    lines: list[str] = []
    for diff in diffs:
        if mode == "compact" and diff.change == "unchanged":
            continue

        marker = f" {diff.marker}" if diff.marker else "    "
        current_display = diff.current or "\u2014"
        proposed_display = diff.proposed or "\u2014"

        if diff.change == "unchanged":
            lines.append(f"    {diff.field:>12}  {current_display}")
        else:
            lines.append(
                f"{marker} {diff.field:>12}  {current_display} \u2192 {proposed_display}"
            )

    return "\n".join(lines)


class MetadataDiff(Widget):
    """Side-by-side metadata comparison widget.

    Modes:
    - "compact": only changed fields, for candidate list preview
    - "full": all fields with change indicators, for confirmation screen
    """

    def __init__(
        self,
        current: BookMetadata,
        proposed: BookMetadata,
        *,
        mode: str = "compact",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._current = current
        self._proposed = proposed
        self._mode = mode

    def update_diff(self, current: BookMetadata, proposed: BookMetadata) -> None:
        """Update the diff with new metadata pair and refresh display."""
        self._current = current
        self._proposed = proposed
        self.refresh()

    def render(self) -> str:
        """Render the metadata diff as formatted text."""
        diffs = compute_field_diffs(self._current, self._proposed)
        return _render_diff_lines(diffs, self._mode)
