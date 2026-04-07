# ABOUTME: Unit tests for resolve_book() lookup helper.
# ABOUTME: Validates ID, substring, ambiguity, and fuzzy-suggestion paths.

from pathlib import Path

import pytest

from bookery.core.book_lookup import (
    Ambiguous,
    Found,
    NotFound,
    Suggestions,
    resolve_book,
)
from bookery.db.mapping import BookRecord
from bookery.metadata.types import BookMetadata


def _record(book_id: int, title: str, author: str = "Anon") -> BookRecord:
    return BookRecord(
        id=book_id,
        metadata=BookMetadata(title=title, authors=[author]),
        file_hash=f"hash{book_id}",
        source_path=Path(f"/src/{book_id}.epub"),
        output_path=Path(f"/out/{book_id}"),
        date_added="2026-01-01",
        date_modified="2026-01-01",
    )


class StubCatalog:
    def __init__(self, records: list[BookRecord]) -> None:
        self._records = records

    def get_by_id(self, book_id: int) -> BookRecord | None:
        for r in self._records:
            if r.id == book_id:
                return r
        return None

    def list_all(self) -> list[BookRecord]:
        return list(self._records)


@pytest.fixture()
def catalog() -> StubCatalog:
    return StubCatalog(
        [
            _record(1, "The Hobbit"),
            _record(2, "The Fellowship of the Ring"),
            _record(3, "The Two Towers"),
            _record(42, "Hitchhiker's Guide to the Galaxy"),
        ]
    )


class TestNumericId:
    def test_known_id_returns_found(self, catalog: StubCatalog) -> None:
        result = resolve_book(catalog, "42")
        assert isinstance(result, Found)
        assert result.record.id == 42

    def test_unknown_id_returns_not_found(self, catalog: StubCatalog) -> None:
        result = resolve_book(catalog, "999")
        assert isinstance(result, NotFound)


class TestSubstringMatch:
    def test_single_substring_hit_returns_found(
        self, catalog: StubCatalog
    ) -> None:
        result = resolve_book(catalog, "Hobbit")
        assert isinstance(result, Found)
        assert result.record.metadata.title == "The Hobbit"

    def test_substring_is_case_insensitive(self, catalog: StubCatalog) -> None:
        result = resolve_book(catalog, "hobbit")
        assert isinstance(result, Found)
        assert result.record.id == 1

    def test_multiple_substring_hits_returns_ambiguous(
        self, catalog: StubCatalog
    ) -> None:
        result = resolve_book(catalog, "the")
        assert isinstance(result, Ambiguous)
        assert len(result.records) >= 2


class TestFuzzyFallback:
    def test_typo_returns_suggestions(self, catalog: StubCatalog) -> None:
        result = resolve_book(catalog, "Hobit")
        assert isinstance(result, Suggestions)
        assert any("Hobbit" in r.metadata.title for r in result.records)

    def test_no_match_at_all_returns_not_found(
        self, catalog: StubCatalog
    ) -> None:
        result = resolve_book(catalog, "qzxqzxqzx")
        assert isinstance(result, NotFound)
