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


class TestBrowseArticleStrippedSort:
    """`browse()` sorts on the persisted article-stripped title (#192).

    Seeds the canonical fixture from the issue — "The Hobbit",
    "A Wizard of Earthsea", "An American Tragedy", "Dune" — and confirms
    title and default (author-primary) orderings ignore leading English
    articles.
    """

    def _seed_articles(self, catalog: LibraryCatalog) -> None:
        # Authors chosen so the author_sort order matches the
        # article-stripped title order (Dreiser < Herbert < Le Guin < Tolkien),
        # which lets the default ordering test reuse the same fixture.
        spec = [
            ("The Hobbit", "Tolkien, J.R.R."),
            ("A Wizard of Earthsea", "Le Guin, Ursula K."),
            ("An American Tragedy", "Dreiser, Theodore"),
            ("Dune", "Herbert, Frank"),
        ]
        for title, author in spec:
            meta = BookMetadata(
                title=title,
                authors=[author],
                author_sort=author,
                source_path=Path(f"/tmp/{title}.epub"),
            )
            catalog.add_book(meta, file_hash=(title * 8).ljust(64, "0"))

    def test_title_asc_ignores_leading_articles(self, catalog):
        self._seed_articles(catalog)
        rows, _ = catalog.browse(sort="title", dir="asc")
        # Sort key: "American Tragedy" < "Dune" < "Hobbit" < "Wizard…".
        assert [r.metadata.title for r in rows] == [
            "An American Tragedy",
            "Dune",
            "The Hobbit",
            "A Wizard of Earthsea",
        ]

    def test_title_desc_ignores_leading_articles(self, catalog):
        self._seed_articles(catalog)
        rows, _ = catalog.browse(sort="title", dir="desc")
        assert [r.metadata.title for r in rows] == [
            "A Wizard of Earthsea",
            "The Hobbit",
            "Dune",
            "An American Tragedy",
        ]

    def test_default_sort_uses_article_stripped_title_as_secondary(self, catalog):
        # Two books by the same author: secondary sort must be article-stripped.
        # Discriminator: raw "Banana" < "The Apple" lexically (B < T) but the
        # article-stripped order is "Apple" < "Banana", so the test fails iff
        # the SQL still sorts on raw title.
        for title in ["Banana", "The Apple"]:
            meta = BookMetadata(
                title=title,
                authors=["Shared, Author"],
                author_sort="Shared, Author",
                source_path=Path(f"/tmp/{title}.epub"),
            )
            catalog.add_book(meta, file_hash=(title * 8).ljust(64, "0"))
        rows, _ = catalog.browse()
        titles = [r.metadata.title for r in rows]
        assert titles == ["The Apple", "Banana"]

    def test_sort_by_added_unaffected_by_articles(self, catalog):
        self._seed_articles(catalog)
        rows, _ = catalog.browse(sort="added", dir="asc")
        ids = [r.id for r in rows]
        # Insertion order — articles have no bearing on added sort.
        assert ids == sorted(ids)


class TestBrowseFilters:
    def _seed_mix(self, catalog: LibraryCatalog) -> dict[str, int]:
        """Seed a fixed catalog and return a name->id map for assertions.

        Mix of formats (epub/pdf), languages (en/fr), and matched status so
        each filter axis has signal to detect.
        """
        spec = [
            ("en-epub-matched", "en", "/tmp/a.epub", True),
            ("en-epub-unmatched", "en", "/tmp/b.epub", False),
            ("fr-epub-matched", "fr", "/tmp/c.epub", True),
            ("en-pdf-unmatched", "en", "/tmp/d.pdf", False),
            ("fr-pdf-matched", "fr", "/tmp/e.pdf", True),
        ]
        name_to_id: dict[str, int] = {}
        for name, lang, path, matched in spec:
            meta = BookMetadata(
                title=name,
                authors=["A"],
                language=lang,
                source_path=Path(path),
            )
            book_id = catalog.add_book(meta, file_hash=name.ljust(64, "0"))
            if matched:
                catalog.set_matched_at(book_id)
            name_to_id[name] = book_id
        return name_to_id

    def test_enriched_1_returns_only_matched_books(self, catalog):
        ids = self._seed_mix(catalog)
        rows, total = catalog.browse(enriched="1")
        titles = {r.metadata.title for r in rows}
        assert titles == {"en-epub-matched", "fr-epub-matched", "fr-pdf-matched"}
        assert total == 3
        del ids

    def test_enriched_0_returns_only_unmatched_books(self, catalog):
        self._seed_mix(catalog)
        rows, total = catalog.browse(enriched="0")
        titles = {r.metadata.title for r in rows}
        assert titles == {"en-epub-unmatched", "en-pdf-unmatched"}
        assert total == 2

    def test_format_epub_matches_path_extension(self, catalog):
        self._seed_mix(catalog)
        rows, total = catalog.browse(format="epub")
        titles = {r.metadata.title for r in rows}
        assert titles == {"en-epub-matched", "en-epub-unmatched", "fr-epub-matched"}
        assert total == 3

    def test_format_pdf_matches_path_extension(self, catalog):
        self._seed_mix(catalog)
        rows, total = catalog.browse(format="pdf")
        titles = {r.metadata.title for r in rows}
        assert titles == {"en-pdf-unmatched", "fr-pdf-matched"}
        assert total == 2

    def test_language_filter_exact_match(self, catalog):
        self._seed_mix(catalog)
        rows, total = catalog.browse(language="fr")
        titles = {r.metadata.title for r in rows}
        assert titles == {"fr-epub-matched", "fr-pdf-matched"}
        assert total == 2

    def test_filters_combine_with_and(self, catalog):
        self._seed_mix(catalog)
        rows, total = catalog.browse(enriched="1", format="epub", language="fr")
        titles = {r.metadata.title for r in rows}
        assert titles == {"fr-epub-matched"}
        assert total == 1

    def test_total_reflects_filters(self, catalog):
        self._seed_mix(catalog)
        _, total = catalog.browse(enriched="0", limit=1)
        # Total counts the filtered set, not the page.
        assert total == 2

    def test_unknown_filter_value_silently_ignored(self, catalog):
        self._seed_mix(catalog)
        # Bogus enriched value should be a no-op (return everything).
        rows, total = catalog.browse(enriched="maybe")
        assert total == 5
        assert len(rows) == 5

    def test_filters_apply_with_search_query(self, catalog):
        self._seed_mix(catalog)
        # FTS search for "epub" appears in titles — combined with enriched=0.
        rows, total = catalog.browse(q="epub", enriched="0")
        titles = {r.metadata.title for r in rows}
        assert titles == {"en-epub-unmatched"}
        assert total == 1

    def test_format_uses_parameter_binding_not_string_interpolation(self, catalog):
        """A malicious format value should not be able to inject SQL.

        We don't expect to ever receive such input (the URL layer whitelists
        format values too), but defense in depth — the catalog must use
        parameter binding so the worst case is "no rows matched".
        """
        self._seed_mix(catalog)
        rows, total = catalog.browse(format="epub'; DROP TABLE books; --")
        assert rows == []
        assert total == 0
        # Sanity: catalog still has its rows.
        all_rows, _ = catalog.browse()
        assert len(all_rows) == 5


class TestBrowseStatusFilter:
    """browse(status=...) filters by book_status row (P3 / #183)."""

    def _seed_status_mix(self, catalog: LibraryCatalog) -> dict[str, int]:
        """Seed three books with distinct read-status states.

        - ``reading`` book has status=1 in ``book_status``.
        - ``finished`` book has status=2.
        - ``unread-explicit`` has status=0.
        - ``unread-implicit`` has no row in ``book_status`` at all — the
          common pre-touch case the CLI ``--unread`` and the web "Unread"
          chip must surface.
        """
        names = ["reading", "finished", "unread-explicit", "unread-implicit"]
        ids: dict[str, int] = {}
        for name in names:
            meta = BookMetadata(
                title=name,
                authors=["A"],
                source_path=Path(f"/tmp/{name}.epub"),
            )
            ids[name] = catalog.add_book(meta, file_hash=name.ljust(64, "0"))
        ts = "2026-05-26T00:00:00"
        catalog.set_book_status(book_id=ids["reading"], status=1, updated_at=ts)
        catalog.set_book_status(book_id=ids["finished"], status=2, updated_at=ts)
        catalog.set_book_status(book_id=ids["unread-explicit"], status=0, updated_at=ts)
        return ids

    def test_status_reading_returns_only_reading_books(self, catalog):
        self._seed_status_mix(catalog)
        rows, total = catalog.browse(status="reading")
        titles = {r.metadata.title for r in rows}
        assert titles == {"reading"}
        assert total == 1

    def test_status_finished_returns_only_finished_books(self, catalog):
        self._seed_status_mix(catalog)
        rows, total = catalog.browse(status="finished")
        titles = {r.metadata.title for r in rows}
        assert titles == {"finished"}
        assert total == 1

    def test_status_unread_includes_implicit_and_explicit(self, catalog):
        self._seed_status_mix(catalog)
        rows, total = catalog.browse(status="unread")
        titles = {r.metadata.title for r in rows}
        # Never-touched (no row) AND status=0 both count as unread.
        assert titles == {"unread-explicit", "unread-implicit"}
        assert total == 2

    def test_status_combines_with_other_filters(self, catalog):
        ids = self._seed_status_mix(catalog)
        catalog.set_matched_at(ids["reading"])
        rows, total = catalog.browse(status="reading", enriched="1")
        titles = {r.metadata.title for r in rows}
        assert titles == {"reading"}
        assert total == 1

        # enriched=0 + reading → reading book is enriched, so result is empty.
        rows, total = catalog.browse(status="reading", enriched="0")
        assert rows == []
        assert total == 0

    def test_status_combines_with_search_query(self, catalog):
        self._seed_status_mix(catalog)
        rows, total = catalog.browse(q="finished", status="finished")
        titles = {r.metadata.title for r in rows}
        assert titles == {"finished"}
        assert total == 1

    def test_unknown_status_value_silently_ignored(self, catalog):
        self._seed_status_mix(catalog)
        rows, total = catalog.browse(status="garbage")
        # Garbage → behaves like no filter, returns everything.
        assert total == 4
        assert len(rows) == 4

    def test_none_status_returns_all_books(self, catalog):
        self._seed_status_mix(catalog)
        rows, total = catalog.browse(status=None)
        assert total == 4
        assert len(rows) == 4
