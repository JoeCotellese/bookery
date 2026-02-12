# ABOUTME: Unit tests for metadata candidate scoring logic.
# ABOUTME: Validates weighted field comparisons, normalization, and edge cases.

from bookery.metadata import BookMetadata
from bookery.metadata.scoring import score_candidate


class TestScoreCandidate:
    """Tests for score_candidate function."""

    def test_identical_metadata_scores_high(self) -> None:
        """Identical title, author, ISBN, and language scores close to 1.0."""
        extracted = BookMetadata(
            title="The Name of the Rose",
            authors=["Umberto Eco"],
            isbn="9780123456472",
            language="en",
        )
        candidate = BookMetadata(
            title="The Name of the Rose",
            authors=["Umberto Eco"],
            isbn="9780123456472",
            language="en",
        )
        score = score_candidate(extracted, candidate)
        assert score >= 0.95

    def test_completely_different_scores_low(self) -> None:
        """Completely unrelated metadata scores near 0.0."""
        extracted = BookMetadata(
            title="War and Peace",
            authors=["Leo Tolstoy"],
            isbn="1111111111",
            language="en",
        )
        candidate = BookMetadata(
            title="Kokoro",
            authors=["Natsume Soseki"],
            isbn="9999999999",
            language="ja",
        )
        score = score_candidate(extracted, candidate)
        assert score < 0.3

    def test_title_has_highest_weight(self) -> None:
        """Title match contributes most to the score."""
        extracted = BookMetadata(title="The Name of the Rose")
        match = BookMetadata(title="The Name of the Rose")
        no_match = BookMetadata(title="Completely Different Book")

        score_match = score_candidate(extracted, match)
        score_no_match = score_candidate(extracted, no_match)
        assert score_match > score_no_match

    def test_case_insensitive_comparison(self) -> None:
        """Comparisons are case-insensitive."""
        extracted = BookMetadata(title="the name of the rose", authors=["UMBERTO ECO"])
        candidate = BookMetadata(title="The Name of the Rose", authors=["Umberto Eco"])
        score = score_candidate(extracted, candidate)
        assert score >= 0.65  # title(0.4) + author(0.3) without ISBN/lang

    def test_author_last_first_normalization(self) -> None:
        """'Last, First' author format is normalized to 'First Last' for comparison."""
        extracted = BookMetadata(title="Test", authors=["Eco, Umberto"])
        candidate = BookMetadata(title="Test", authors=["Umberto Eco"])
        score = score_candidate(extracted, candidate)
        # Title is exact (0.4) + author normalized match (0.3) = 0.7
        assert score >= 0.65

    def test_isbn_strips_hyphens_and_spaces(self) -> None:
        """ISBN comparison ignores hyphens and spaces."""
        extracted = BookMetadata(title="Test", isbn="978-0-12-345647-2")
        candidate = BookMetadata(title="Test", isbn="9780123456472")
        score = score_candidate(extracted, candidate)
        # Title match (0.4) + ISBN match (0.2) = 0.6
        assert score >= 0.55

    def test_score_clamped_to_zero_one(self) -> None:
        """Score is always in [0.0, 1.0]."""
        extracted = BookMetadata(title="X")
        candidate = BookMetadata(title="Y")
        score = score_candidate(extracted, candidate)
        assert 0.0 <= score <= 1.0

    def test_missing_isbn_does_not_penalize(self) -> None:
        """When extracted has no ISBN, ISBN component contributes zero (not negative)."""
        extracted = BookMetadata(title="The Name of the Rose", authors=["Umberto Eco"])
        candidate = BookMetadata(
            title="The Name of the Rose",
            authors=["Umberto Eco"],
            isbn="9780123456472",
        )
        score = score_candidate(extracted, candidate)
        # Should still be high: title(0.4) + author(0.3) = 0.7
        assert score >= 0.65

    def test_language_match_contributes(self) -> None:
        """Matching language adds to the score."""
        extracted = BookMetadata(title="Test", language="en")
        candidate_en = BookMetadata(title="Test", language="en")
        candidate_fr = BookMetadata(title="Test", language="fr")

        score_en = score_candidate(extracted, candidate_en)
        score_fr = score_candidate(extracted, candidate_fr)
        assert score_en > score_fr

    def test_multiple_authors_compared(self) -> None:
        """Multiple authors are joined and compared as a single string."""
        extracted = BookMetadata(
            title="Good Omens", authors=["Terry Pratchett", "Neil Gaiman"]
        )
        candidate = BookMetadata(
            title="Good Omens", authors=["Terry Pratchett", "Neil Gaiman"]
        )
        score = score_candidate(extracted, candidate)
        assert score >= 0.65
