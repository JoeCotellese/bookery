# ABOUTME: LibraryCatalog.browse() — paginated list/search against a real SQLite.
# ABOUTME: Covers offset/limit, FTS5 q matching, and total-count semantics.

from pathlib import Path

import pytest

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


@pytest.fixture
def catalog(tmp_path: Path):
    conn = open_library(tmp_path / "lib.db")
    try:
        yield LibraryCatalog(conn)
    finally:
        conn.close()


def _seed_n(catalog: LibraryCatalog, n: int) -> None:
    """Insert ``n`` books with predictable titles and author_sort keys."""
    for i in range(n):
        meta = BookMetadata(
            title=f"Title {i:03d}",
            authors=[f"Author {i:03d}"],
            source_path=Path(f"/tmp/book-{i:03d}.epub"),
        )
        catalog.add_book(meta, file_hash=f"hash-{i:03d}".ljust(64, "0"))


class TestBrowsePagination:
    def test_empty_catalog_returns_empty_list_zero_total(self, catalog):
        rows, total = catalog.browse()
        assert rows == []
        assert total == 0

    def test_total_is_independent_of_limit(self, catalog):
        _seed_n(catalog, 25)
        _, total = catalog.browse(limit=5)
        assert total == 25

    def test_limit_caps_returned_rows(self, catalog):
        _seed_n(catalog, 25)
        rows, _ = catalog.browse(limit=10)
        assert len(rows) == 10

    def test_offset_skips_rows(self, catalog):
        _seed_n(catalog, 25)
        page1, _ = catalog.browse(limit=10, offset=0)
        page2, _ = catalog.browse(limit=10, offset=10)
        page3, _ = catalog.browse(limit=10, offset=20)
        ids1 = [r.id for r in page1]
        ids2 = [r.id for r in page2]
        assert len(set(ids1) & set(ids2)) == 0
        assert len(page3) == 5

    def test_offset_past_end_returns_empty_but_total_nonzero(self, catalog):
        _seed_n(catalog, 3)
        rows, total = catalog.browse(limit=10, offset=100)
        assert rows == []
        assert total == 3

    def test_default_ordering_is_by_author_then_title(self, catalog):
        for title, author in [
            ("Zebra", "Adams, John"),
            ("Apple", "Brown, Dan"),
            ("Banana", "Adams, John"),
        ]:
            meta = BookMetadata(
                title=title,
                authors=[author],
                author_sort=author,
                source_path=Path(f"/tmp/{title}.epub"),
            )
            catalog.add_book(meta, file_hash=(title * 8).ljust(64, "0"))
        rows, _ = catalog.browse()
        titles = [r.metadata.title for r in rows]
        # Adams's Banana before Zebra (both Adams), then Brown's Apple.
        assert titles == ["Banana", "Zebra", "Apple"]


class TestBrowseSearch:
    def test_q_filters_by_fts_match(self, catalog):
        for title, author in [
            ("The Rose Garden", "Smith"),
            ("A Different Book", "Jones"),
            ("Another Rose Story", "Lee"),
        ]:
            meta = BookMetadata(
                title=title, authors=[author], source_path=Path(f"/tmp/{title}.epub")
            )
            catalog.add_book(meta, file_hash=(title * 8).ljust(64, "0"))
        rows, total = catalog.browse(q="rose")
        titles = sorted(r.metadata.title for r in rows)
        assert titles == ["Another Rose Story", "The Rose Garden"]
        assert total == 2

    def test_q_with_fts_punctuation_does_not_crash(self, catalog):
        """User input like 'dune:' is FTS5 column-filter syntax that crashes
        sqlite if passed through raw. browse() must treat it as plain text."""
        meta = BookMetadata(
            title="Dune Chronicles",
            authors=["Herbert"],
            source_path=Path("/tmp/dune.epub"),
        )
        catalog.add_book(meta, file_hash="dune".ljust(64, "0"))
        # All of these are valid user input that previously raised
        # sqlite3.OperationalError because FTS5 reserves these characters.
        for raw in ["dune:", 'dune"', "dune AND", "AND", "*foo", "(dune)"]:
            rows, total = catalog.browse(q=raw)
            assert isinstance(rows, list)
            assert isinstance(total, int)

    def test_q_multi_word_still_matches(self, catalog):
        """Phrase-escaping per token must preserve implicit AND across tokens."""
        for title in ["The Rose Garden", "Rose of Sharon", "Garden Tools"]:
            meta = BookMetadata(title=title, authors=["A"], source_path=Path(f"/tmp/{title}.epub"))
            catalog.add_book(meta, file_hash=(title * 8).ljust(64, "0"))
        rows, total = catalog.browse(q="rose garden")
        titles = [r.metadata.title for r in rows]
        assert "The Rose Garden" in titles
        assert "Garden Tools" not in titles
        assert "Rose of Sharon" not in titles
        assert total == 1

    def test_q_with_pagination(self, catalog):
        for i in range(5):
            meta = BookMetadata(
                title=f"Rose Book {i}",
                authors=[f"Author {i}"],
                source_path=Path(f"/tmp/rose-{i}.epub"),
            )
            catalog.add_book(meta, file_hash=f"rose-{i}".ljust(64, "0"))
        # Unrelated row should not be counted in the q total.
        catalog.add_book(
            BookMetadata(title="Tulip", authors=["A"], source_path=Path("/tmp/tulip.epub")),
            file_hash="tulip".ljust(64, "0"),
        )
        rows, total = catalog.browse(q="rose", limit=2, offset=0)
        assert total == 5
        assert len(rows) == 2


class TestBrowseSort:
    def _seed_three(self, catalog: LibraryCatalog) -> None:
        for title, author in [
            ("Apple", "Zelda"),
            ("Banana", "Adams"),
            ("Cherry", "Murphy"),
        ]:
            meta = BookMetadata(
                title=title,
                authors=[author],
                author_sort=author,
                source_path=Path(f"/tmp/{title}.epub"),
            )
            catalog.add_book(meta, file_hash=(title * 8).ljust(64, "0"))

    def test_sort_by_title_asc(self, catalog):
        self._seed_three(catalog)
        rows, _ = catalog.browse(sort="title", dir="asc")
        assert [r.metadata.title for r in rows] == ["Apple", "Banana", "Cherry"]

    def test_sort_by_title_desc(self, catalog):
        self._seed_three(catalog)
        rows, _ = catalog.browse(sort="title", dir="desc")
        assert [r.metadata.title for r in rows] == ["Cherry", "Banana", "Apple"]

    def test_sort_by_author_asc(self, catalog):
        self._seed_three(catalog)
        rows, _ = catalog.browse(sort="author", dir="asc")
        assert [r.metadata.author_sort for r in rows] == ["Adams", "Murphy", "Zelda"]

    def test_sort_by_author_desc(self, catalog):
        self._seed_three(catalog)
        rows, _ = catalog.browse(sort="author", dir="desc")
        assert [r.metadata.author_sort for r in rows] == ["Zelda", "Murphy", "Adams"]

    def test_sort_by_added_desc_newest_first(self, catalog):
        # Inserts happen in order; date_added defaults to "now". Use ids to
        # confirm newest-first ordering since timestamps may collide at
        # sub-second resolution.
        self._seed_three(catalog)
        rows, _ = catalog.browse(sort="added", dir="desc")
        ids = [r.id for r in rows]
        assert ids == sorted(ids, reverse=True)

    def test_sort_by_added_asc_oldest_first(self, catalog):
        self._seed_three(catalog)
        rows, _ = catalog.browse(sort="added", dir="asc")
        ids = [r.id for r in rows]
        assert ids == sorted(ids)

    def test_unknown_sort_falls_back_to_default(self, catalog):
        self._seed_three(catalog)
        # Unknown key should not crash; behaves like default (author asc).
        rows, _ = catalog.browse(sort="bogus", dir="desc")
        assert len(rows) == 3
