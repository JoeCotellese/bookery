# ABOUTME: Unit tests for the rematch command argument validation and book selection.
# ABOUTME: Tests mutual exclusion of selectors and _select_books helper logic.

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click import UsageError

from bookery.cli.commands.rematch_cmd import _select_books, _validate_selectors
from bookery.db.mapping import BookRecord
from bookery.metadata.types import BookMetadata


def _make_record(
    book_id: int,
    title: str = "Test Book",
    source_path: str = "/tmp/test.epub",
    output_path: str | None = None,
) -> BookRecord:
    """Create a minimal BookRecord for testing."""
    return BookRecord(
        id=book_id,
        metadata=BookMetadata(title=title, authors=["Author"]),
        file_hash="abc123",
        source_path=Path(source_path),
        output_path=Path(output_path) if output_path else None,
        date_added="2024-01-01T00:00:00",
        date_modified="2024-01-01T00:00:00",
    )


class TestValidateSelectors:
    """Tests for argument mutual exclusion validation."""

    def test_rejects_no_arguments(self) -> None:
        """No id, no --all, no --tag raises UsageError."""
        with pytest.raises(UsageError, match="Specify exactly one"):
            _validate_selectors(book_id=None, match_all=False, tag_name=None)

    def test_rejects_id_with_all(self) -> None:
        """book_id + --all raises UsageError."""
        with pytest.raises(UsageError, match="Specify exactly one"):
            _validate_selectors(book_id=1, match_all=True, tag_name=None)

    def test_rejects_id_with_tag(self) -> None:
        """book_id + --tag raises UsageError."""
        with pytest.raises(UsageError, match="Specify exactly one"):
            _validate_selectors(book_id=1, match_all=False, tag_name="fiction")

    def test_rejects_all_with_tag(self) -> None:
        """--all + --tag raises UsageError."""
        with pytest.raises(UsageError, match="Specify exactly one"):
            _validate_selectors(book_id=None, match_all=True, tag_name="fiction")

    def test_accepts_id_only(self) -> None:
        """Single book_id is valid."""
        _validate_selectors(book_id=1, match_all=False, tag_name=None)

    def test_accepts_all_only(self) -> None:
        """--all alone is valid."""
        _validate_selectors(book_id=None, match_all=True, tag_name=None)

    def test_accepts_tag_only(self) -> None:
        """--tag alone is valid."""
        _validate_selectors(book_id=None, match_all=False, tag_name="fiction")


class TestSelectBooks:
    """Tests for _select_books helper."""

    def test_select_books_single_id(self) -> None:
        """Returns one BookRecord when given a valid ID."""
        record = _make_record(42, title="Found Book")
        catalog = MagicMock()
        catalog.get_by_id.return_value = record

        books = _select_books(catalog, book_id=42, match_all=False, tag_name=None)

        assert len(books) == 1
        assert books[0].id == 42

    def test_select_books_all(self) -> None:
        """Returns all books from catalog."""
        records = [_make_record(1), _make_record(2), _make_record(3)]
        catalog = MagicMock()
        catalog.list_all.return_value = records

        books = _select_books(catalog, book_id=None, match_all=True, tag_name=None)

        assert len(books) == 3

    def test_select_books_by_tag(self) -> None:
        """Returns books matching the tag."""
        records = [_make_record(1), _make_record(2)]
        catalog = MagicMock()
        catalog.get_books_by_tag.return_value = records

        books = _select_books(catalog, book_id=None, match_all=False, tag_name="fiction")

        assert len(books) == 2
        catalog.get_books_by_tag.assert_called_once_with("fiction")

    def test_select_books_unknown_id(self) -> None:
        """Returns empty list for unknown ID."""
        catalog = MagicMock()
        catalog.get_by_id.return_value = None

        books = _select_books(catalog, book_id=999, match_all=False, tag_name=None)

        assert books == []

    def test_select_books_unknown_tag(self) -> None:
        """Raises ValueError for unknown tag."""
        catalog = MagicMock()
        catalog.get_books_by_tag.side_effect = ValueError("Tag 'nope' not found")

        with pytest.raises(ValueError, match="not found"):
            _select_books(catalog, book_id=None, match_all=False, tag_name="nope")
