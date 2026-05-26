# ABOUTME: Unit tests for the article-stripping helper used by title_sort and vault filing.
# ABOUTME: Covers leading-article stripping, case insensitivity, and empty-result fallback.

import pytest

from bookery.core.text_sort import LEADING_ARTICLE_RE, compute_title_sort


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
