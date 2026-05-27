# ABOUTME: Unit tests for the article-stripping helper used by title_sort and vault filing.
# ABOUTME: Covers leading-article stripping, case insensitivity, and empty-result fallback.

import pytest

from bookery.core.text_sort import (
    LEADING_ARTICLE_RE,
    compute_author_sort,
    compute_title_sort,
)


class TestComputeTitleSort:
    @pytest.mark.parametrize(
        "title,expected",
        [
            ("The Hobbit", "Hobbit"),
            ("A Wizard of Earthsea", "Wizard of Earthsea"),
            ("An American Tragedy", "American Tragedy"),
            ("Dune", "Dune"),
            ("The Lord of the Rings", "Lord of the Rings"),
        ],
    )
    def test_strips_leading_english_articles(self, title: str, expected: str) -> None:
        assert compute_title_sort(title) == expected

    def test_case_insensitive(self) -> None:
        assert compute_title_sort("the hobbit") == "hobbit"
        assert compute_title_sort("THE HOBBIT") == "HOBBIT"
        assert compute_title_sort("aN american thing") == "american thing"

    def test_only_leading_article_stripped(self) -> None:
        # Only the first leading article — "The The" loses one "The".
        assert compute_title_sort("The The") == "The"
        # An article in the middle is untouched.
        assert compute_title_sort("Once and the Future King") == "Once and the Future King"

    def test_no_article_returns_original(self) -> None:
        assert compute_title_sort("Hobbit") == "Hobbit"
        assert compute_title_sort("1984") == "1984"

    def test_article_without_following_word_falls_back(self) -> None:
        # Bare "The" / "An" with no following text shouldn't disappear.
        assert compute_title_sort("The") == "The"
        assert compute_title_sort("An") == "An"
        assert compute_title_sort("A") == "A"

    def test_empty_string_returns_empty(self) -> None:
        assert compute_title_sort("") == ""

    def test_preserves_internal_whitespace(self) -> None:
        # Multi-space between article and rest is collapsed by .strip() at the
        # match boundary but interior whitespace stays as-is.
        assert compute_title_sort("The  Hobbit") == "Hobbit"
        assert compute_title_sort("The Hobbit  and Bilbo") == "Hobbit  and Bilbo"

    def test_word_starting_with_article_letters_not_stripped(self) -> None:
        # "Theater" should not lose "The"; "Another" should not lose "An";
        # "Apple" should not lose "A". The regex requires whitespace after.
        assert compute_title_sort("Theater of War") == "Theater of War"
        assert compute_title_sort("Another Country") == "Another Country"
        assert compute_title_sort("Apple Pie") == "Apple Pie"


class TestLeadingArticleRe:
    def test_pattern_is_exported(self) -> None:
        # Vault assemble.py reuses this. Lock the import contract.
        assert LEADING_ARTICLE_RE.match("The Hobbit") is not None
        assert LEADING_ARTICLE_RE.match("Hobbit") is None


class TestComputeAuthorSort:
    """Author-side twin of compute_title_sort. Mirrors derive_author_sort's rules
    so it can be reused both at write-time (mapping.py) and during the V10
    migration backfill (issue #196)."""

    def test_explicit_value_wins(self) -> None:
        """An explicit author_sort always overrides the derived value."""
        assert compute_author_sort(["Umberto Eco"], "Eco, Umberto") == "Eco, Umberto"

    def test_explicit_value_overrides_even_when_unrelated(self) -> None:
        """The helper trusts the caller — it does not re-derive when an
        explicit value is supplied."""
        assert compute_author_sort(["Madonna"], "Curator Override") == "Curator Override"

    def test_empty_explicit_falls_through_to_derivation(self) -> None:
        """Empty string for the explicit slot is treated as "no value" so we
        still derive — matches `derive_author_sort`'s `if metadata.author_sort:`
        truthiness check."""
        assert compute_author_sort(["Umberto Eco"], "") == "Eco, Umberto"

    def test_none_explicit_falls_through_to_derivation(self) -> None:
        assert compute_author_sort(["Umberto Eco"], None) == "Eco, Umberto"

    def test_empty_authors_returns_unknown(self) -> None:
        assert compute_author_sort([]) == "Unknown"

    def test_first_author_whitespace_only_returns_unknown(self) -> None:
        assert compute_author_sort(["   "]) == "Unknown"

    def test_two_word_name_inverts(self) -> None:
        assert compute_author_sort(["Umberto Eco"]) == "Eco, Umberto"

    def test_three_word_name_inverts_on_last_token(self) -> None:
        assert compute_author_sort(["Gabriel Garcia Marquez"]) == "Marquez, Gabriel Garcia"

    def test_single_word_kept_as_is(self) -> None:
        assert compute_author_sort(["Madonna"]) == "Madonna"

    def test_comma_containing_name_kept_as_is(self) -> None:
        """Pre-inverted "Last, First" stays as-is — no double inversion."""
        assert compute_author_sort(["Eco, Umberto"]) == "Eco, Umberto"

    def test_only_first_author_considered(self) -> None:
        """Co-authors are ignored; sort key derives from the first listed name
        — same convention as `derive_author_sort`."""
        assert compute_author_sort(["Neil Gaiman", "Terry Pratchett"]) == "Gaiman, Neil"

    def test_strips_surrounding_whitespace_before_deciding(self) -> None:
        """Leading/trailing whitespace on the first author is ignored when
        classifying single-token vs multi-token."""
        assert compute_author_sort(["  Umberto Eco  "]) == "Eco, Umberto"
