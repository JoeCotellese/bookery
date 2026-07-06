# ABOUTME: Unit tests for heuristic series inference from title patterns.
# ABOUTME: Verifies pattern extraction, negatives, and provenance stamping.

import pytest

from bookery.metadata.series_heuristic import (
    SeriesGuess,
    apply_series_heuristic,
    infer_series_from_title,
)
from bookery.metadata.types import BookMetadata


class TestInferSeriesFromTitle:
    @pytest.mark.parametrize(
        "title,expected",
        [
            ("Foo (Series #3)", SeriesGuess("Series", 3.0)),
            ("Foo (The Long Saga #12)", SeriesGuess("The Long Saga", 12.0)),
            ("Foo (Series, Book 3)", SeriesGuess("Series", 3.0)),
            ("Foo (Series Book 3)", SeriesGuess("Series", 3.0)),
            ("Foo (Series, #3.5)", SeriesGuess("Series", 3.5)),
            ("The Eye of the World, Book 1", SeriesGuess("The Eye of the World", 1.0)),
            ("Foo: A Bar Novel", SeriesGuess("Bar", None)),
            ("Foo: A Bar Mystery", SeriesGuess("Bar", None)),
        ],
    )
    def test_positive_patterns(self, title: str, expected: SeriesGuess) -> None:
        assert infer_series_from_title(title) == expected

    @pytest.mark.parametrize(
        "title",
        [
            "The Eye of the World",
            "Stand by Me",
            "Dune (1965)",  # parenthetical year is not a series
            "Report (Final #3 Draft) Continued",  # pattern must anchor at end
            "A Novel Approach",  # "Novel" not in the ': A X Novel' shape
            "",
        ],
    )
    def test_negatives(self, title: str) -> None:
        assert infer_series_from_title(title) is None


class TestApplySeriesHeuristic:
    def test_fills_empty_series_and_stamps_provenance(self) -> None:
        meta = BookMetadata(title="Foo (Series #3)")

        applied = apply_series_heuristic(meta)

        assert applied is True
        assert meta.series == "Series"
        assert meta.series_index == 3.0
        assert meta.identifiers["provenance_series"] == "heuristic"
        assert meta.identifiers["provenance_series_index"] == "heuristic"

    def test_name_only_pattern_stamps_series_provenance_only(self) -> None:
        meta = BookMetadata(title="Foo: A Bar Novel")

        applied = apply_series_heuristic(meta)

        assert applied is True
        assert meta.series == "Bar"
        assert meta.series_index is None
        assert meta.identifiers["provenance_series"] == "heuristic"
        assert "provenance_series_index" not in meta.identifiers

    def test_does_not_overwrite_provider_series(self) -> None:
        meta = BookMetadata(title="Foo (Series #3)", series="Real Series", series_index=1.0)

        applied = apply_series_heuristic(meta)

        assert applied is False
        assert meta.series == "Real Series"
        assert meta.series_index == 1.0
        assert "provenance_series" not in meta.identifiers

    def test_no_pattern_no_change(self) -> None:
        meta = BookMetadata(title="The Eye of the World")

        applied = apply_series_heuristic(meta)

        assert applied is False
        assert meta.series is None
        assert meta.identifiers == {}
