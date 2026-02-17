# ABOUTME: Unit tests for metadata candidate scoring logic.
# ABOUTME: Validates weighted field comparisons, normalization, and edge cases.

from bookery.metadata import BookMetadata
from bookery.metadata.scoring import completeness_bonus, score_candidate


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
        assert score >= 0.95  # title+author weights redistributed to fill 1.0

    def test_author_last_first_normalization(self) -> None:
        """'Last, First' author format is normalized to 'First Last' for comparison."""
        extracted = BookMetadata(title="Test", authors=["Eco, Umberto"])
        candidate = BookMetadata(title="Test", authors=["Umberto Eco"])
        score = score_candidate(extracted, candidate)
        # Title+author weights redistributed → near 1.0
        assert score >= 0.95

    def test_isbn_strips_hyphens_and_spaces(self) -> None:
        """ISBN comparison ignores hyphens and spaces."""
        extracted = BookMetadata(title="Test", isbn="978-0-12-345647-2")
        candidate = BookMetadata(title="Test", isbn="9780123456472")
        score = score_candidate(extracted, candidate)
        # Title+ISBN weights redistributed → near 1.0
        assert score >= 0.95

    def test_score_clamped_to_zero_one(self) -> None:
        """Score is always in [0.0, 1.0]."""
        extracted = BookMetadata(title="X")
        candidate = BookMetadata(title="Y")
        score = score_candidate(extracted, candidate)
        assert 0.0 <= score <= 1.0

    def test_missing_isbn_does_not_penalize(self) -> None:
        """When extracted has no ISBN, its weight is redistributed — score stays high."""
        extracted = BookMetadata(title="The Name of the Rose", authors=["Umberto Eco"])
        candidate = BookMetadata(
            title="The Name of the Rose",
            authors=["Umberto Eco"],
            isbn="9780123456472",
        )
        score = score_candidate(extracted, candidate)
        # ISBN weight redistributed to title+author → near 1.0 + completeness bonus
        assert score >= 0.95

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
        assert score >= 0.95

    def test_missing_isbn_redistributes_weight(self) -> None:
        """Perfect title+author with no ISBN should score near 1.0 (weight redistributed)."""
        extracted = BookMetadata(
            title="The Name of the Rose",
            authors=["Umberto Eco"],
            language="en",
        )
        candidate = BookMetadata(
            title="The Name of the Rose",
            authors=["Umberto Eco"],
            isbn="9780123456472",
            language="en",
        )
        score = score_candidate(extracted, candidate)
        # ISBN weight (0.2) redistributed across title, author, language
        # Base match should be >= 0.95 before completeness bonus
        assert score >= 0.95

    def test_missing_language_redistributes_weight(self) -> None:
        """Perfect title+author, no ISBN, no language → score near 1.0."""
        extracted = BookMetadata(
            title="The Name of the Rose",
            authors=["Umberto Eco"],
        )
        candidate = BookMetadata(
            title="The Name of the Rose",
            authors=["Umberto Eco"],
        )
        score = score_candidate(extracted, candidate)
        # Both ISBN and language weights redistributed to title+author
        assert score >= 0.95

    def test_mismatched_isbn_still_penalizes(self) -> None:
        """When both sides have ISBN but they differ, score should be lower than a match."""
        extracted = BookMetadata(
            title="The Name of the Rose",
            authors=["Umberto Eco"],
            isbn="9780123456472",
            language="en",
        )
        matching_isbn = BookMetadata(
            title="The Name of the Rose",
            authors=["Umberto Eco"],
            isbn="9780123456472",
            language="en",
        )
        mismatched_isbn = BookMetadata(
            title="The Name of the Rose",
            authors=["Umberto Eco"],
            isbn="9789999999999",
            language="en",
        )
        score_match = score_candidate(extracted, matching_isbn)
        score_mismatch = score_candidate(extracted, mismatched_isbn)
        assert score_match > score_mismatch

    def test_completeness_bonus_boosts_rich_candidates(self) -> None:
        """Candidates with more populated fields score higher than sparse ones."""
        extracted = BookMetadata(title="Alexandria Link")
        sparse = BookMetadata(title="Alexandria Link", authors=["Steve Berry"])
        rich = BookMetadata(
            title="Alexandria Link",
            authors=["Steve Berry"],
            description="Cotton Malone races to find the lost Library.",
            isbn="9780345485762",
        )
        score_sparse = score_candidate(extracted, sparse)
        score_rich = score_candidate(extracted, rich)
        assert score_rich > score_sparse

    def test_completeness_bonus_is_a_tiebreaker(self) -> None:
        """Completeness bonus never overrides a significantly better match score."""
        extracted = BookMetadata(title="Alexandria Link", authors=["Steve Berry"])
        good_match_sparse = BookMetadata(
            title="Alexandria Link", authors=["Steve Berry"]
        )
        bad_match_rich = BookMetadata(
            title="Totally Different Book",
            authors=["Other Author"],
            description="A long description.",
            isbn="9780000000000",
            publisher="Big Publisher",
            language="eng",
        )
        score_good = score_candidate(extracted, good_match_sparse)
        score_bad = score_candidate(extracted, bad_match_rich)
        assert score_good > score_bad


class TestCompletenessBonus:
    """Tests for the completeness_bonus function."""

    def test_empty_metadata_returns_zero(self) -> None:
        """Metadata with no optional fields filled returns 0.0."""
        meta = BookMetadata(title="Test")
        assert completeness_bonus(meta) == 0.0

    def test_description_has_highest_weight(self) -> None:
        """Description contributes the most to the completeness bonus."""
        with_desc = BookMetadata(title="Test", description="A description.")
        with_publisher = BookMetadata(title="Test", publisher="Publisher")
        assert completeness_bonus(with_desc) > completeness_bonus(with_publisher)

    def test_all_fields_returns_max_bonus(self) -> None:
        """Metadata with all completeness fields filled returns the max bonus."""
        meta = BookMetadata(
            title="Test",
            authors=["Author"],
            description="Desc.",
            isbn="1234567890",
            language="eng",
            publisher="Publisher",
        )
        bonus = completeness_bonus(meta)
        assert bonus == 0.10

    def test_isbn_weighted_higher_than_language(self) -> None:
        """ISBN contributes more to completeness than language."""
        with_isbn = BookMetadata(title="Test", isbn="1234567890")
        with_lang = BookMetadata(title="Test", language="eng")
        assert completeness_bonus(with_isbn) > completeness_bonus(with_lang)

    def test_bonus_scales_with_fields(self) -> None:
        """More filled fields means a higher bonus."""
        one_field = BookMetadata(title="Test", description="Desc.")
        two_fields = BookMetadata(title="Test", description="Desc.", isbn="123")
        assert completeness_bonus(two_fields) > completeness_bonus(one_field)
