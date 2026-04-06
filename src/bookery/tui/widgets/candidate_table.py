# ABOUTME: CandidateTable widget displaying ranked metadata candidates.
# ABOUTME: Shows confidence scores, tier labels, and source info in a DataTable.

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable

from bookery.metadata.candidate import MetadataCandidate

_HIGH_THRESHOLD = 0.8
_MEDIUM_THRESHOLD = 0.5


def confidence_tier(confidence: float) -> str:
    """Map a confidence score to a tier label (HIGH/MED/LOW)."""
    if confidence >= _HIGH_THRESHOLD:
        return "HIGH"
    if confidence >= _MEDIUM_THRESHOLD:
        return "MED"
    return "LOW"


class CandidateTable(Widget):
    """A DataTable of ranked MetadataCandidates with confidence scores."""

    can_focus_children = True

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._candidates: list[MetadataCandidate] = []

    def compose(self) -> ComposeResult:
        yield DataTable(id="candidate-table")

    def on_mount(self) -> None:
        table = self.query_one("#candidate-table", DataTable)
        table.add_column("#", key="index", width=3)
        table.add_column("Title", key="title")
        table.add_column("Author", key="author")
        table.add_column("ISBN", key="isbn", width=16)
        table.add_column("Lang", key="language", width=5)
        table.add_column("Confidence", key="confidence", width=12)
        table.add_column("Source", key="source", width=12)
        table.cursor_type = "row"

    def load(self, candidates: list[MetadataCandidate]) -> None:
        """Populate the table with candidates."""
        self._candidates = list(candidates)
        table = self.query_one("#candidate-table", DataTable)
        table.clear()

        for i, candidate in enumerate(candidates, start=1):
            conf_pct = f"{candidate.confidence:.0%}"
            tier = confidence_tier(candidate.confidence)
            table.add_row(
                str(i),
                candidate.metadata.title,
                candidate.metadata.author,
                candidate.metadata.isbn or "\u2014",
                candidate.metadata.language or "\u2014",
                f"{conf_pct} {tier}",
                candidate.source,
                key=str(i - 1),
            )

    def get_candidate_at(self, index: int) -> MetadataCandidate | None:
        """Get the candidate at the given index."""
        if 0 <= index < len(self._candidates):
            return self._candidates[index]
        return None

    @property
    def candidates(self) -> list[MetadataCandidate]:
        """The currently loaded candidates."""
        return self._candidates
