# ABOUTME: Unit tests for path formatting, sanitization, and directory structure.
# ABOUTME: Validates sanitize_component, derive_author_sort, build_output_path, resolve_collision.

from pathlib import Path

from bookery.core.pathformat import (
    build_output_path,
    derive_author_sort,
    is_processed,
    record_processed,
    resolve_collision,
    sanitize_component,
)
from bookery.metadata.types import BookMetadata


class TestSanitizeComponent:
    """Tests for sanitize_component()."""

    def test_replaces_unsafe_chars(self) -> None:
        """Unsafe filesystem chars are replaced with dashes."""
        assert sanitize_component('foo/bar\\baz:qux*?\"<>|') == "foo-bar-baz-qux"

    def test_collapses_runs_of_dashes(self) -> None:
        """Multiple consecutive dashes are collapsed to one."""
        assert sanitize_component("foo---bar") == "foo-bar"

    def test_collapses_runs_of_whitespace(self) -> None:
        """Multiple consecutive spaces are collapsed to one."""
        assert sanitize_component("foo   bar") == "foo bar"

    def test_strips_leading_trailing_dots_spaces_dashes(self) -> None:
        """Leading/trailing dots, spaces, and dashes are stripped."""
        assert sanitize_component("  ..--Hello World--.  ") == "Hello World"

    def test_truncates_to_255_bytes(self) -> None:
        """Result is at most 255 bytes in UTF-8, without splitting codepoints."""
        # Each emoji is 4 bytes in UTF-8
        long_name = "\U0001F4DA" * 100  # 400 bytes
        result = sanitize_component(long_name)
        assert len(result.encode("utf-8")) <= 255
        # Should not have partial codepoints
        result.encode("utf-8").decode("utf-8")

    def test_empty_after_sanitization_returns_fallback(self) -> None:
        """Empty string after sanitization returns fallback."""
        assert sanitize_component("///***") == "Unknown"

    def test_custom_fallback(self) -> None:
        """Custom fallback string is used when result is empty."""
        assert sanitize_component("///", fallback="Untitled") == "Untitled"

    def test_nfc_normalization(self) -> None:
        """Unicode is NFC-normalized."""
        # 'e' + combining acute accent -> single codepoint
        decomposed = "caf\u0065\u0301"
        result = sanitize_component(decomposed)
        assert result == "caf\u00e9"


class TestDeriveAuthorSort:
    """Tests for derive_author_sort()."""

    def test_uses_author_sort_when_present(self) -> None:
        """Uses author_sort field directly if present."""
        meta = BookMetadata(title="T", author_sort="Eco, Umberto")
        assert derive_author_sort(meta) == "Eco, Umberto"

    def test_inverts_two_word_name(self) -> None:
        """Inverts 'First Last' to 'Last, First'."""
        meta = BookMetadata(title="T", authors=["Umberto Eco"])
        assert derive_author_sort(meta) == "Eco, Umberto"

    def test_single_word_name_kept_as_is(self) -> None:
        """Single-word name like 'Madonna' stays unchanged."""
        meta = BookMetadata(title="T", authors=["Madonna"])
        assert derive_author_sort(meta) == "Madonna"

    def test_name_with_comma_kept_as_is(self) -> None:
        """Name already containing a comma is used as-is."""
        meta = BookMetadata(title="T", authors=["Eco, Umberto"])
        assert derive_author_sort(meta) == "Eco, Umberto"

    def test_no_author_sort_empty_authors(self) -> None:
        """No author_sort and empty authors -> 'Unknown'."""
        meta = BookMetadata(title="T", authors=[])
        assert derive_author_sort(meta) == "Unknown"

    def test_multi_word_name(self) -> None:
        """Three-word name inverts on last word."""
        meta = BookMetadata(title="T", authors=["Gabriel Garcia Marquez"])
        assert derive_author_sort(meta) == "Marquez, Gabriel Garcia"


class TestBuildOutputPath:
    """Tests for build_output_path()."""

    def test_normal_case(self, tmp_path: Path) -> None:
        """Builds author_sort/title.epub path."""
        meta = BookMetadata(
            title="The Name of the Rose",
            authors=["Umberto Eco"],
        )
        result = build_output_path(meta, tmp_path)
        assert result == tmp_path / "Eco, Umberto" / "The Name of the Rose.epub"

    def test_missing_author(self, tmp_path: Path) -> None:
        """Missing author falls back to 'Unknown'."""
        meta = BookMetadata(title="Orphan Book", authors=[])
        result = build_output_path(meta, tmp_path)
        assert result == tmp_path / "Unknown" / "Orphan Book.epub"

    def test_missing_title(self, tmp_path: Path) -> None:
        """Empty title falls back to 'Untitled'."""
        meta = BookMetadata(title="", authors=["Author Name"])
        result = build_output_path(meta, tmp_path)
        assert result == tmp_path / "Name, Author" / "Untitled.epub"

    def test_unsafe_chars_in_title_author(self, tmp_path: Path) -> None:
        """Unsafe chars in title and author are sanitized."""
        meta = BookMetadata(
            title="What? Why! How*",
            authors=["A/B C"],
        )
        result = build_output_path(meta, tmp_path)
        assert "/" not in result.stem
        assert "*" not in result.stem
        assert "?" not in result.stem

    def test_custom_extension(self, tmp_path: Path) -> None:
        """Custom extension can be specified."""
        meta = BookMetadata(title="Test", authors=["Author"])
        result = build_output_path(meta, tmp_path, extension=".kepub.epub")
        assert result.name == "Test.kepub.epub"


class TestResolveCollision:
    """Tests for resolve_collision()."""

    def test_no_collision(self, tmp_path: Path) -> None:
        """Returns original path when no collision exists."""
        target = tmp_path / "book.epub"
        assert resolve_collision(target) == target

    def test_single_collision(self, tmp_path: Path) -> None:
        """Appends _1 when target exists."""
        target = tmp_path / "book.epub"
        target.write_text("existing")
        result = resolve_collision(target)
        assert result == tmp_path / "book_1.epub"

    def test_multiple_collisions(self, tmp_path: Path) -> None:
        """Increments suffix for multiple collisions."""
        target = tmp_path / "book.epub"
        target.write_text("existing")
        (tmp_path / "book_1.epub").write_text("also existing")
        result = resolve_collision(target)
        assert result == tmp_path / "book_2.epub"


class TestProcessedManifest:
    """Tests for record_processed() and is_processed()."""

    def test_not_processed_initially(self, tmp_path: Path) -> None:
        """Returns False when nothing has been recorded."""
        assert is_processed(tmp_path, "book.epub") is False

    def test_record_and_check(self, tmp_path: Path) -> None:
        """Records a file and then finds it."""
        record_processed(tmp_path, "book.epub")
        assert is_processed(tmp_path, "book.epub") is True

    def test_different_file_not_found(self, tmp_path: Path) -> None:
        """A different filename is not found."""
        record_processed(tmp_path, "book.epub")
        assert is_processed(tmp_path, "other.epub") is False

    def test_multiple_records(self, tmp_path: Path) -> None:
        """Multiple files can be recorded and found."""
        record_processed(tmp_path, "a.epub")
        record_processed(tmp_path, "b.epub")
        assert is_processed(tmp_path, "a.epub") is True
        assert is_processed(tmp_path, "b.epub") is True

    def test_creates_output_dir(self, tmp_path: Path) -> None:
        """Creates the output directory if it doesn't exist."""
        output_dir = tmp_path / "new_dir"
        record_processed(output_dir, "book.epub")
        assert output_dir.exists()
        assert is_processed(output_dir, "book.epub") is True
