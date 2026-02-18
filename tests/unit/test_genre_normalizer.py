# ABOUTME: Unit tests for the genre normalization system.
# ABOUTME: Tests canonical genres, subject mapping, regex patterns, and vote counting.

from bookery.metadata.genres import (
    CANONICAL_GENRES,
    GenreNormalizationResult,
    is_canonical_genre,
    normalize_subject,
    normalize_subjects,
)


class TestCanonicalGenres:
    """Tests for the CANONICAL_GENRES constant."""

    def test_has_14_entries(self) -> None:
        """There are exactly 14 canonical genres."""
        assert len(CANONICAL_GENRES) == 14

    def test_all_unique(self) -> None:
        """All canonical genre names are unique."""
        assert len(set(CANONICAL_GENRES)) == 14


class TestNormalizeSubject:
    """Tests for normalize_subject()."""

    def test_exact_match(self) -> None:
        """Exact lowercase subject maps to canonical genre."""
        assert normalize_subject("fiction") == "Literary Fiction"

    def test_exact_match_case_insensitive(self) -> None:
        """Subject matching is case-insensitive."""
        assert normalize_subject("Fiction") == "Literary Fiction"
        assert normalize_subject("SCIENCE FICTION") == "Science Fiction"

    def test_regex_fallback_sci_fi(self) -> None:
        """Regex patterns catch common abbreviations."""
        assert normalize_subject("sci-fi") == "Science Fiction"

    def test_regex_fallback_detective(self) -> None:
        """Regex catches detective-related subjects."""
        assert normalize_subject("detective stories") == "Mystery & Thriller"

    def test_unknown_subject_returns_none(self) -> None:
        """Unknown subjects return None."""
        assert normalize_subject("underwater basket weaving") is None

    def test_empty_string_returns_none(self) -> None:
        """Empty string returns None."""
        assert normalize_subject("") is None

    def test_romance_mapping(self) -> None:
        """Romance-related subjects map correctly."""
        assert normalize_subject("love stories") == "Romance"

    def test_history_mapping(self) -> None:
        """History subjects map correctly."""
        assert normalize_subject("history") == "History & Biography"

    def test_self_help_mapping(self) -> None:
        """Self-help subjects map correctly."""
        assert normalize_subject("self-help") == "Self-Help & Personal Development"

    def test_childrens_mapping(self) -> None:
        """Children's literature maps correctly."""
        assert normalize_subject("children's literature") == "Children's & Middle Grade"


class TestNormalizeSubjects:
    """Tests for normalize_subjects()."""

    def test_vote_counting_picks_most_common(self) -> None:
        """Primary genre is the one with the most subject matches."""
        # "fiction", "literary fiction" both -> Literary Fiction
        # "murder" -> Mystery & Thriller
        result = normalize_subjects(["fiction", "literary fiction", "murder"])
        assert isinstance(result, GenreNormalizationResult)
        assert result.primary_genre == "Literary Fiction"

    def test_tie_breaking_first_appearance(self) -> None:
        """When genres tie in votes, the first-appearing genre wins."""
        # "horror" -> Horror, "romance" -> Romance (1 each, Horror first)
        result = normalize_subjects(["horror fiction", "love stories"])
        assert result.primary_genre == "Horror"

    def test_unmatched_collected(self) -> None:
        """Subjects that don't match any genre are collected in unmatched."""
        result = normalize_subjects(["fiction", "xyzzy123"])
        assert "xyzzy123" in result.unmatched
        assert "fiction" not in result.unmatched

    def test_all_unmatched(self) -> None:
        """When no subjects match, primary_genre is None."""
        result = normalize_subjects(["xyzzy", "abcde"])
        assert result.primary_genre is None
        assert len(result.matches) == 0
        assert len(result.unmatched) == 2

    def test_empty_subjects(self) -> None:
        """Empty list returns empty result."""
        result = normalize_subjects([])
        assert result.primary_genre is None
        assert result.matches == []
        assert result.unmatched == []

    def test_matches_contain_genre_and_method(self) -> None:
        """Each match has subject, genre, and method fields."""
        result = normalize_subjects(["fiction"])
        assert len(result.matches) == 1
        match = result.matches[0]
        assert match.subject == "fiction"
        assert match.genre == "Literary Fiction"
        assert match.method in ("exact", "regex")


class TestIsCanonicalGenre:
    """Tests for is_canonical_genre()."""

    def test_valid_genre(self) -> None:
        """A genre from CANONICAL_GENRES returns True."""
        assert is_canonical_genre("Literary Fiction") is True

    def test_invalid_genre(self) -> None:
        """A non-canonical genre returns False."""
        assert is_canonical_genre("Made Up Genre") is False

    def test_case_insensitive(self) -> None:
        """Genre check is case-insensitive."""
        assert is_canonical_genre("literary fiction") is True
        assert is_canonical_genre("SCIENCE FICTION") is True
