# ABOUTME: Heuristic series inference from title patterns.
# ABOUTME: Fires only when providers left series NULL; provenance is "heuristic".

import re
from dataclasses import dataclass

from bookery.metadata.types import BookMetadata

HEURISTIC_SOURCE = "heuristic"

# Ordered: first match wins. Bare "Series: Name" is deliberately unsupported —
# a colon usually separates title from subtitle, so it would false-positive
# far more than it would help.
_TITLE_PATTERNS = (
    # "Foo (Series #3)", "Foo (Series, Book 3)", "Foo (Series Book 3)", "Foo (Series, #3.5)"
    re.compile(r"\((?P<series>[^()#]+?),?\s+(?:#|Book\s+)(?P<index>\d+(?:\.\d+)?)\)\s*$"),
    # "Foo, Book 1"
    re.compile(r"^(?P<series>.+?),\s+Book\s+(?P<index>\d+(?:\.\d+)?)\s*$"),
    # "Foo: A Bar Novel" / "Foo: A Bar Mystery" — series name, no position
    re.compile(r":\s+A\s+(?P<series>.+?)\s+(?:Novel|Mystery)\s*$"),
)


@dataclass(frozen=True)
class SeriesGuess:
    """A series name (and optional position) inferred from a title."""

    series: str
    series_index: float | None = None


def infer_series_from_title(title: str) -> SeriesGuess | None:
    """Extract a series guess from common title patterns, or None."""
    for pattern in _TITLE_PATTERNS:
        match = pattern.search(title)
        if not match:
            continue
        series = match.group("series").strip()
        if not series:
            continue
        groups = match.groupdict()
        index = float(groups["index"]) if groups.get("index") else None
        return SeriesGuess(series=series, series_index=index)
    return None


def apply_series_heuristic(metadata: BookMetadata) -> bool:
    """Fill empty series fields from the title pattern, stamping heuristic provenance.

    Mutates ``metadata`` in place. Never overwrites an existing series value,
    so provider results (and user edits upstream) always win. Returns True
    when a guess was applied.
    """
    if metadata.series:
        return False

    guess = infer_series_from_title(metadata.title or "")
    if guess is None:
        return False

    metadata.series = guess.series
    metadata.identifiers["provenance_series"] = HEURISTIC_SOURCE
    if guess.series_index is not None and metadata.series_index is None:
        metadata.series_index = guess.series_index
        metadata.identifiers["provenance_series_index"] = HEURISTIC_SOURCE
    return True
