# ABOUTME: Unit tests for filter_redundant_mobis() deduplication logic.
# ABOUTME: Verifies MOBIs are skipped when an EPUB exists in the same directory.

from pathlib import Path

from bookery.core.dedup import filter_redundant_mobis


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
