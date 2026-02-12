# ABOUTME: Unit tests for metadata normalization of mangled EPUB titles.
# ABOUTME: Validates CamelCase splitting, word segmentation, author detection, and pipeline.

from pathlib import Path

from bookery.metadata import BookMetadata
from bookery.metadata.normalizer import (
    NormalizationResult,
    _detect_author_in_title,
    _is_likely_person_name,
    _needs_normalization,
    _split_camel_case,
    normalize_metadata,
    split_concatenated,
)


class TestNeedsNormalization:
    """Tests for _needs_normalization quick-check function."""

    def test_clean_title_does_not_need_normalization(self) -> None:
        """A properly spaced title should not need normalization."""
        assert _needs_normalization("The Name of the Rose") is False

    def test_camel_case_needs_normalization(self) -> None:
        """CamelCase-joined words need normalization."""
        assert _needs_normalization("TheTemplarLegacy") is True

    def test_long_spaceless_string_needs_normalization(self) -> None:
        """A long string with no spaces needs normalization."""
        assert _needs_normalization("thetemplarlegacy") is True

    def test_short_single_word_does_not_need_normalization(self) -> None:
        """Short single words like '1984' or 'Dune' are fine as-is."""
        assert _needs_normalization("Dune") is False
        assert _needs_normalization("1984") is False

    def test_legitimate_hyphen_does_not_need_normalization(self) -> None:
        """Titles like 'Catch-22' with legitimate hyphens are fine."""
        assert _needs_normalization("Catch-22") is False

    def test_author_dash_title_needs_normalization(self) -> None:
        """'SteveBerry-TheTemplarLegacy' pattern needs normalization."""
        assert _needs_normalization("SteveBerry-TheTemplarLegacy") is True

    def test_underscore_joined_needs_normalization(self) -> None:
        """Underscore-joined words need normalization."""
        assert _needs_normalization("The_Templar_Legacy") is True

    def test_empty_string_does_not_need_normalization(self) -> None:
        """Empty string should not need normalization."""
        assert _needs_normalization("") is False

    def test_whitespace_only_does_not_need_normalization(self) -> None:
        """Whitespace-only should not need normalization."""
        assert _needs_normalization("   ") is False


class TestSplitCamelCase:
    """Tests for _split_camel_case regex splitting."""

    def test_simple_camel_case(self) -> None:
        """Split simple CamelCase into separate words."""
        assert _split_camel_case("TheTemplarLegacy") == ["The", "Templar", "Legacy"]

    def test_proper_nouns_consecutive_uppercase(self) -> None:
        """Handle consecutive uppercase letters (acronyms)."""
        assert _split_camel_case("HTMLParser") == ["HTML", "Parser"]

    def test_digits_at_boundary(self) -> None:
        """Split on letter-to-digit and digit-to-letter boundaries."""
        assert _split_camel_case("Fahrenheit451") == ["Fahrenheit", "451"]

    def test_no_camel_case(self) -> None:
        """String without CamelCase returns as single element."""
        assert _split_camel_case("legacy") == ["legacy"]

    def test_all_uppercase(self) -> None:
        """All-caps string stays as one word."""
        assert _split_camel_case("NASA") == ["NASA"]

    def test_person_name(self) -> None:
        """Person names split on case boundaries."""
        assert _split_camel_case("SteveBerry") == ["Steve", "Berry"]

    def test_mixed_digits_and_letters(self) -> None:
        """Digit-to-uppercase boundary splits."""
        assert _split_camel_case("Book2Read") == ["Book", "2", "Read"]


class TestSplitConcatenated:
    """Tests for split_concatenated full pipeline."""

    def test_camel_case_title(self) -> None:
        """CamelCase title becomes space-separated words."""
        assert split_concatenated("TheTemplarLegacy") == "The Templar Legacy"

    def test_hyphen_separated_segments(self) -> None:
        """Hyphen-separated CamelCase segments are split and joined."""
        assert split_concatenated("SteveBerry-TheTemplarLegacy") == (
            "Steve Berry The Templar Legacy"
        )

    def test_underscore_separated(self) -> None:
        """Underscores are replaced and segments split."""
        assert split_concatenated("The_Templar_Legacy") == "The Templar Legacy"

    def test_already_clean(self) -> None:
        """Clean titles pass through unchanged."""
        assert split_concatenated("The Templar Legacy") == "The Templar Legacy"

    def test_lowercase_concatenated_uses_wordninja(self) -> None:
        """All-lowercase concatenated text is split using wordninja."""
        result = split_concatenated("thetemplarlegacy")
        # wordninja should produce something reasonable with spaces
        assert " " in result
        assert "templar" in result.lower()

    def test_single_word(self) -> None:
        """Single words pass through unchanged."""
        assert split_concatenated("Dune") == "Dune"

    def test_digits_in_title(self) -> None:
        """Letter-digit boundaries are handled."""
        result = split_concatenated("Fahrenheit451")
        assert "Fahrenheit" in result
        assert "451" in result


class TestIsLikelyPersonName:
    """Tests for _is_likely_person_name heuristic."""

    def test_two_word_capitalized_name(self) -> None:
        """Two capitalized words look like a person name."""
        assert _is_likely_person_name("Steve Berry") is True

    def test_three_word_name(self) -> None:
        """Three capitalized words look like a person name."""
        assert _is_likely_person_name("Mary Higgins Clark") is True

    def test_single_word_not_a_name(self) -> None:
        """Single word does not look like a person name."""
        assert _is_likely_person_name("Steve") is False

    def test_contains_stop_words(self) -> None:
        """Phrases with common stop words are not person names."""
        assert _is_likely_person_name("The Great Gatsby") is False

    def test_too_many_words(self) -> None:
        """More than 3 words is unlikely to be a person name."""
        assert _is_likely_person_name("One Two Three Four") is False

    def test_lowercase_words_not_a_name(self) -> None:
        """All-lowercase words are not person names."""
        assert _is_likely_person_name("steve berry") is False

    def test_initials_in_name(self) -> None:
        """Names with initials are recognized."""
        assert _is_likely_person_name("J K Rowling") is True


class TestDetectAuthorInTitle:
    """Tests for _detect_author_in_title extraction."""

    def test_author_dash_title_pattern(self) -> None:
        """First segment that looks like a name is extracted as author."""
        title, author = _detect_author_in_title("Steve Berry The Templar Legacy")
        assert author == "Steve Berry"
        assert title == "The Templar Legacy"

    def test_clean_title_no_author(self) -> None:
        """Clean title without embedded author returns None for author."""
        title, author = _detect_author_in_title("The Templar Legacy")
        assert author is None
        assert title == "The Templar Legacy"

    def test_legitimate_title_with_capitalized_words(self) -> None:
        """Titles with stop words are not mistaken for author names."""
        title, author = _detect_author_in_title("The Great Gatsby")
        assert author is None
        assert title == "The Great Gatsby"

    def test_single_word_title(self) -> None:
        """Single word title has no embedded author."""
        title, author = _detect_author_in_title("Dune")
        assert author is None
        assert title == "Dune"

    def test_three_word_author_name(self) -> None:
        """Three-word author name is detected."""
        title, author = _detect_author_in_title(
            "Mary Higgins Clark Silent Night"
        )
        assert author == "Mary Higgins Clark"
        assert title == "Silent Night"


class TestNormalizeMetadata:
    """Tests for normalize_metadata full pipeline."""

    def test_clean_metadata_passes_through(self) -> None:
        """Clean metadata is not modified."""
        meta = BookMetadata(
            title="The Name of the Rose",
            authors=["Umberto Eco"],
            isbn="9780156001311",
        )
        result = normalize_metadata(meta)
        assert result.was_modified is False
        assert result.normalized.title == "The Name of the Rose"
        assert result.normalized.authors == ["Umberto Eco"]
        assert result.original is meta

    def test_embedded_author_extracted(self) -> None:
        """Author embedded in CamelCase title is extracted when authors list is empty."""
        meta = BookMetadata(title="SteveBerry-TheTemplarLegacy")
        result = normalize_metadata(meta)
        assert result.was_modified is True
        assert "Steve Berry" in result.normalized.authors
        assert "Templar" in result.normalized.title
        assert "Legacy" in result.normalized.title

    def test_unknown_author_replaced(self) -> None:
        """Author detected when existing author is 'Unknown'."""
        meta = BookMetadata(
            title="SteveBerry-TheTemplarLegacy",
            authors=["Unknown"],
        )
        result = normalize_metadata(meta)
        assert result.was_modified is True
        assert "Steve Berry" in result.normalized.authors
        assert "Unknown" not in result.normalized.authors

    def test_existing_author_preserved(self) -> None:
        """When authors are already set, embedded author is not extracted."""
        meta = BookMetadata(
            title="TheTemplarLegacy",
            authors=["Steve Berry"],
        )
        result = normalize_metadata(meta)
        assert result.was_modified is True
        assert result.normalized.authors == ["Steve Berry"]
        assert "Templar" in result.normalized.title

    def test_isbn_and_source_path_preserved(self) -> None:
        """ISBN, source_path, and other fields are preserved through normalization."""
        meta = BookMetadata(
            title="TheTemplarLegacy",
            isbn="9780345504500",
            source_path=Path("/books/test.epub"),
            language="en",
            publisher="Ballantine",
        )
        result = normalize_metadata(meta)
        assert result.normalized.isbn == "9780345504500"
        assert result.normalized.source_path == Path("/books/test.epub")
        assert result.normalized.language == "en"
        assert result.normalized.publisher == "Ballantine"

    def test_original_metadata_immutable(self) -> None:
        """Original metadata is not mutated by normalization."""
        meta = BookMetadata(title="SteveBerry-TheTemplarLegacy")
        result = normalize_metadata(meta)
        assert meta.title == "SteveBerry-TheTemplarLegacy"
        assert meta.authors == []
        assert result.original is meta

    def test_result_dataclass_fields(self) -> None:
        """NormalizationResult has the expected fields."""
        meta = BookMetadata(title="Test")
        result = normalize_metadata(meta)
        assert isinstance(result, NormalizationResult)
        assert hasattr(result, "original")
        assert hasattr(result, "normalized")
        assert hasattr(result, "was_modified")
