# ABOUTME: Unit tests for deduplication logic: MOBI filtering and metadata normalization.
# ABOUTME: Covers filter_redundant_mobis and normalize_for_dedup/author/isbn functions.

from pathlib import Path

from bookery.core.dedup import (
    filter_redundant_mobis,
    normalize_author_for_dedup,
    normalize_for_dedup,
    normalize_isbn,
)


class TestFilterRedundantMobis:
    """Tests for MOBI deduplication based on EPUB co-location."""

    def test_mobi_skipped_when_epub_in_same_dir(self, tmp_path: Path) -> None:
        """MOBI + EPUB in same directory → MOBI is skipped."""
        book_dir = tmp_path / "Author" / "Title"
        book_dir.mkdir(parents=True)
        mobi = book_dir / "book.mobi"
        epub = book_dir / "book.epub"
        mobi.touch()
        epub.touch()

        to_convert, skipped = filter_redundant_mobis([mobi], [epub])

        assert to_convert == []
        assert skipped == [mobi]

    def test_mobi_kept_when_alone_in_dir(self, tmp_path: Path) -> None:
        """MOBI alone in directory → kept for conversion."""
        mobi_dir = tmp_path / "Author" / "Title"
        mobi_dir.mkdir(parents=True)
        mobi = mobi_dir / "book.mobi"
        mobi.touch()

        # EPUB is in a different directory
        other_dir = tmp_path / "Other" / "Book"
        other_dir.mkdir(parents=True)
        epub = other_dir / "other.epub"
        epub.touch()

        to_convert, skipped = filter_redundant_mobis([mobi], [epub])

        assert to_convert == [mobi]
        assert skipped == []

    def test_mobi_skipped_with_multiple_epubs_in_dir(
        self, tmp_path: Path,
    ) -> None:
        """Multiple EPUBs + MOBI in same dir → MOBI is skipped."""
        book_dir = tmp_path / "Author" / "Title"
        book_dir.mkdir(parents=True)
        mobi = book_dir / "book.mobi"
        epub1 = book_dir / "book.epub"
        epub2 = book_dir / "book_v2.epub"
        mobi.touch()
        epub1.touch()
        epub2.touch()

        to_convert, skipped = filter_redundant_mobis([mobi], [epub1, epub2])

        assert to_convert == []
        assert skipped == [mobi]

    def test_mobi_skipped_even_with_different_filename(
        self, tmp_path: Path,
    ) -> None:
        """MOBI filename doesn't match EPUB → still skipped (same dir)."""
        book_dir = tmp_path / "Author" / "Title"
        book_dir.mkdir(parents=True)
        mobi = book_dir / "converted.mobi"
        epub = book_dir / "original.epub"
        mobi.touch()
        epub.touch()

        to_convert, skipped = filter_redundant_mobis([mobi], [epub])

        assert to_convert == []
        assert skipped == [mobi]

    def test_mixed_dirs_correct_split(self, tmp_path: Path) -> None:
        """Some dirs have EPUBs, some don't → correct partition."""
        # Dir with both formats
        dir_both = tmp_path / "A" / "Both"
        dir_both.mkdir(parents=True)
        mobi_skip = dir_both / "book.mobi"
        epub = dir_both / "book.epub"
        mobi_skip.touch()
        epub.touch()

        # Dir with only MOBI
        dir_mobi = tmp_path / "B" / "MobiOnly"
        dir_mobi.mkdir(parents=True)
        mobi_keep = dir_mobi / "another.mobi"
        mobi_keep.touch()

        to_convert, skipped = filter_redundant_mobis(
            [mobi_skip, mobi_keep], [epub],
        )

        assert to_convert == [mobi_keep]
        assert skipped == [mobi_skip]

    def test_empty_inputs(self) -> None:
        """Empty lists → empty results."""
        to_convert, skipped = filter_redundant_mobis([], [])

        assert to_convert == []
        assert skipped == []

    def test_no_epubs_all_mobis_kept(self, tmp_path: Path) -> None:
        """No EPUBs at all → all MOBIs kept."""
        dir_a = tmp_path / "A"
        dir_a.mkdir()
        mobi = dir_a / "book.mobi"
        mobi.touch()

        to_convert, skipped = filter_redundant_mobis([mobi], [])

        assert to_convert == [mobi]
        assert skipped == []


class TestNormalizeForDedup:
    """Tests for title normalization."""

    def test_strips_leading_the(self) -> None:
        assert normalize_for_dedup("The Name of the Rose") == "name of the rose"

    def test_strips_leading_a(self) -> None:
        assert normalize_for_dedup("A Tale of Two Cities") == "tale of two cities"

    def test_strips_leading_an(self) -> None:
        assert normalize_for_dedup("An Unexpected Journey") == "unexpected journey"

    def test_collapses_whitespace(self) -> None:
        assert normalize_for_dedup("  A  Tale of  Two Cities  ") == "tale of two cities"

    def test_lowercases(self) -> None:
        assert normalize_for_dedup("DUNE") == "dune"

    def test_empty_string(self) -> None:
        assert normalize_for_dedup("") == ""

    def test_only_article(self) -> None:
        """A bare article with no trailing word is kept as-is (lowercased)."""
        assert normalize_for_dedup("The") == "the"

    def test_article_not_stripped_mid_title(self) -> None:
        """Only leading articles are stripped, not mid-title ones."""
        result = normalize_for_dedup("Murder on the Orient Express")
        assert result == "murder on the orient express"


class TestNormalizeAuthorForDedup:
    """Tests for author name normalization."""

    def test_first_last_to_last_first(self) -> None:
        assert normalize_author_for_dedup("Umberto Eco") == "eco, umberto"

    def test_already_inverted(self) -> None:
        assert normalize_author_for_dedup("Eco, Umberto") == "eco, umberto"

    def test_lowercases(self) -> None:
        assert normalize_author_for_dedup("J.R.R. Tolkien") == "tolkien, j.r.r."

    def test_empty_string(self) -> None:
        assert normalize_author_for_dedup("") == ""

    def test_single_name(self) -> None:
        """Mononymous authors stay as-is (lowercased)."""
        assert normalize_author_for_dedup("Voltaire") == "voltaire"

    def test_multiple_spaces(self) -> None:
        assert normalize_author_for_dedup("  Frank  Herbert  ") == "herbert, frank"


class TestNormalizeIsbn:
    """Tests for ISBN normalization."""

    def test_strips_hyphens(self) -> None:
        assert normalize_isbn("978-0-15-144647-6") == "9780151446476"

    def test_isbn10_to_isbn13(self) -> None:
        assert normalize_isbn("0151446474") == "9780151446476"

    def test_isbn13_passthrough(self) -> None:
        assert normalize_isbn("9780151446476") == "9780151446476"

    def test_strips_spaces(self) -> None:
        assert normalize_isbn("978 0 15 144647 6") == "9780151446476"

    def test_empty_string(self) -> None:
        assert normalize_isbn("") == ""

    def test_none_returns_empty(self) -> None:
        assert normalize_isbn(None) == ""  # type: ignore[arg-type]

    def test_isbn10_with_hyphens(self) -> None:
        assert normalize_isbn("0-15-144647-4") == "9780151446476"
