# ABOUTME: Unit tests for the title-correspondence predicate gating series acceptance (#303).
# ABOUTME: Covers the audit's mismatched pairs, Book N prefixes, and legitimate edition drift.

import pytest

from bookery.metadata.title_correspondence import (
    Correspondence,
    comparison_key,
    leading_book_number,
    titles_correspond,
)


class TestComparisonKey:
    def test_strips_case_punctuation_and_leading_article(self) -> None:
        assert comparison_key("The Eye of the World!") == "eye of the world"

    def test_splits_mangled_concatenated_titles(self) -> None:
        assert "templar" in comparison_key("SteveBerry-TheTemplarLegacy")

    def test_leaves_ordinary_titles_intact(self) -> None:
        assert comparison_key("Cannery Row") == "cannery row"


class TestLeadingBookNumber:
    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("Book 18 - Force Heretic II - Refugee", 18.0),
            ("Book 2 - The Force Unleashed II", 2.0),
            ("book 5 \u2013 Trapped", 5.0),
            ("Vol. 3: Foo", 3.0),
            ("Part 1 - Target", 1.0),
        ],
    )
    def test_extracts_prefix_number(self, title: str, expected: float) -> None:
        assert leading_book_number(title) == expected

    @pytest.mark.parametrize(
        "title",
        [
            "The Eye of the World",
            "Booked for Murder",
            "",
            "A Storm of Swords",
        ],
    )
    def test_returns_none_without_a_prefix(self, title: str) -> None:
        assert leading_book_number(title) is None


class TestUnrelatedCandidatesRejected:
    """The seven Pattern A rows from the #301 audit — series from a different book."""

    @pytest.mark.parametrize(
        ("book_title", "candidate_title"),
        [
            ("Book 18 - Force Heretic II - Refugee", "Bjørn Hansen: A Novel"),
            ("Book 19 - Force Heretic III - Reunion", "Hellraiser: Book of the Damned"),
            ("Book 17 - Force Heretic I - Remnant", "Expeditionary Force: Match Game"),
            ("Book 2 - The Force Unleashed II", "The Old Guard: Force Multiplied"),
            ("The End of All Things #2: This Hollow Union", "Valkyrie: Jane Foster Vol. 2"),
            ("Book 5 - Trapped", "Aquilon: The Water Mage"),
            ("Book 1 - Target", "The Book of Biff: Volume One"),
        ],
    )
    def test_audit_pairs_do_not_correspond(self, book_title: str, candidate_title: str) -> None:
        verdict = titles_correspond(book_title, candidate_title)

        assert verdict.corresponds is False
        assert candidate_title in verdict.reason

    def test_reason_names_both_titles(self) -> None:
        verdict = titles_correspond("Book 5 - Trapped", "Aquilon: The Water Mage")

        assert "Aquilon: The Water Mage" in verdict.reason
        assert "Book 5 - Trapped" in verdict.reason


class TestGenuineMatchesAccepted:
    @pytest.mark.parametrize(
        ("book_title", "candidate_title"),
        [
            ("The Eye of the World", "The Eye of the World"),
            ("The Eye of the World", "Eye of the World"),
            # Edition/subtitle drift — same book, longer provider title.
            (
                "Stranger In a Strange Land - Original Uncut Version",
                "Stranger in a Strange Land",
            ),
            ("Raising Steam", "Raising Steam: A Discworld Novel"),
            ("Naked in Death", "Naked In Death (In Death, Book 1)"),
            ("The Way of Kings", "The Way of Kings: Book One of the Stormlight Archive"),
            # Book N prefix, but the remainder really is the candidate's title.
            ("Book 17 - Force Heretic I - Remnant", "Force Heretic I: Remnant"),
            ("SteveBerry-TheTemplarLegacy", "The Templar Legacy"),
        ],
    )
    def test_same_book_corresponds(self, book_title: str, candidate_title: str) -> None:
        assert titles_correspond(book_title, candidate_title).corresponds is True


class TestMissingTitles:
    @pytest.mark.parametrize(
        ("book_title", "candidate_title"),
        [("", "The Eye of the World"), ("The Eye of the World", ""), ("", "")],
    )
    def test_blank_side_cannot_correspond(self, book_title: str, candidate_title: str) -> None:
        verdict = titles_correspond(book_title, candidate_title)

        assert verdict.corresponds is False
        assert "missing a title" in verdict.reason


class TestOverlapFloor:
    def test_a_single_shared_numeral_is_not_enough(self) -> None:
        """Containment must not fire on one incidental token — the #2 coincidence."""
        verdict = titles_correspond("The End of All Things #2", "Valkyrie 2")

        assert verdict.corresponds is False

    def test_verdict_is_frozen(self) -> None:
        verdict = titles_correspond("Dune", "Dune")

        assert isinstance(verdict, Correspondence)
        with pytest.raises(AttributeError):
            verdict.corresponds = False  # type: ignore[misc]
