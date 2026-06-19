# ABOUTME: Unit tests for rule-based collection membership resolution on LibraryCatalog.
# ABOUTME: Covers the V14 query column, the resolver, preview, and static<->rule conversion.

from pathlib import Path

import pytest

from bookery.collections import CollectionQueryError
from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata


@pytest.fixture()
def catalog(tmp_path: Path) -> LibraryCatalog:
    conn = open_library(tmp_path / "resolver_test.db")
    return LibraryCatalog(conn)


def _add(
    catalog: LibraryCatalog,
    title: str,
    *,
    series: str | None = None,
    genre: str | None = None,
    authors: list[str] | None = None,
    language: str | None = None,
    publisher: str | None = None,
    isbn: str | None = None,
    subjects: list[str] | None = None,
    tag: str | None = None,
    published_date: str | None = None,
    rating: float | None = None,
    date_added: str | None = None,
) -> int:
    book_id = catalog.add_book(
        BookMetadata(
            title=title,
            series=series,
            authors=authors or [],
            language=language,
            publisher=publisher,
            isbn=isbn,
            subjects=subjects or [],
            published_date=published_date,
            rating=rating,
            source_path=Path(f"/books/{title}.epub"),
        ),
        file_hash=f"hash_{title}",
    )
    if genre is not None:
        catalog.add_genre(book_id, genre, is_primary=True)
    if tag is not None:
        catalog.add_tag(book_id, tag)
    if date_added is not None:
        # date_added is DB-managed (defaults to now); override it for added: tests.
        catalog._conn.execute(
            "UPDATE books SET date_added = ? WHERE id = ?", (date_added, book_id)
        )
        catalog._conn.commit()
    return book_id


def _query_of(catalog: LibraryCatalog, collection_id: int) -> object:
    collection = catalog.get_collection_by_id(collection_id)
    assert collection is not None
    return collection["query"]


class TestMigrationV14:
    def test_query_column_exists(self, tmp_path: Path) -> None:
        conn = open_library(tmp_path / "v14.db")
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(collections)")}
        assert "query" in cols
        conn.close()


class TestQueryStorage:
    def test_create_without_query_is_static(self, catalog: LibraryCatalog) -> None:
        cid = catalog.create_collection("Manual")
        assert _query_of(catalog, cid) is None

    def test_create_with_query_is_rule_based(self, catalog: LibraryCatalog) -> None:
        cid = catalog.create_collection("Sci-Fi", query='genre:"Science Fiction"')
        assert _query_of(catalog, cid) == 'genre:"Science Fiction"'


class TestResolveMembers:
    def test_static_resolves_to_collection_books(self, catalog: LibraryCatalog) -> None:
        a = _add(catalog, "A")
        b = _add(catalog, "B")
        cid = catalog.create_collection("Manual")
        catalog.add_books_to_collection(cid, [a, b])
        assert sorted(catalog.resolve_collection_member_ids(cid)) == sorted([a, b])

    def test_rule_series_equality_is_case_insensitive(self, catalog: LibraryCatalog) -> None:
        d1 = _add(catalog, "Dune", series="Dune")
        d2 = _add(catalog, "Dune Messiah", series="dune")
        _add(catalog, "Neuromancer", series="Sprawl")
        cid = catalog.create_collection("Dune books", query='series:"Dune"')
        assert sorted(catalog.resolve_collection_member_ids(cid)) == sorted([d1, d2])

    def test_rule_genre_join(self, catalog: LibraryCatalog) -> None:
        sf1 = _add(catalog, "SF One", genre="Science Fiction")
        sf2 = _add(catalog, "SF Two", genre="Science Fiction")
        _add(catalog, "A Fantasy", genre="Fantasy")
        cid = catalog.create_collection("Sci-Fi", query='genre:"Science Fiction"')
        assert sorted(catalog.resolve_collection_member_ids(cid)) == sorted([sf1, sf2])

    def test_resolve_members_returns_records_ordered_by_title_sort(
        self, catalog: LibraryCatalog
    ) -> None:
        _add(catalog, "The Border", series="Edge")  # title_sort "Border"
        _add(catalog, "Apex", series="Edge")
        cid = catalog.create_collection("Edge", query="series:Edge")
        titles = [r.metadata.title for r in catalog.resolve_collection_members(cid)]
        assert titles == ["Apex", "The Border"]

    def test_unknown_collection_raises(self, catalog: LibraryCatalog) -> None:
        with pytest.raises(ValueError):
            catalog.resolve_collection_member_ids(999)

    def test_get_collection_books_uses_resolver_for_rule_based(
        self, catalog: LibraryCatalog
    ) -> None:
        sf = _add(catalog, "SF One", genre="Science Fiction")
        cid = catalog.create_collection("Sci-Fi", query='genre:"Science Fiction"')
        assert [r.id for r in catalog.get_collection_books(cid)] == [sf]


class TestScalarFieldRules:
    def test_author_contains_matches_substring(self, catalog: LibraryCatalog) -> None:
        a = _add(catalog, "Fellowship", authors=["J.R.R. Tolkien"])
        b = _add(catalog, "Silmarillion", authors=["J.R.R. Tolkien", "Christopher Tolkien"])
        _add(catalog, "Narnia", authors=["C.S. Lewis"])
        cid = catalog.create_collection("Tolkien", query="author:Tolkien")
        assert sorted(catalog.resolve_collection_member_ids(cid)) == sorted([a, b])

    def test_subject_contains_matches_substring(self, catalog: LibraryCatalog) -> None:
        d = _add(catalog, "1984", subjects=["Dystopian fiction", "Politics"])
        _add(catalog, "Pride", subjects=["Romance"])
        cid = catalog.create_collection("Dystopia", query="subject:Dystopian")
        assert catalog.resolve_collection_member_ids(cid) == [d]

    def test_title_prefix_is_left_anchored(self, catalog: LibraryCatalog) -> None:
        d1 = _add(catalog, "Dune")
        d2 = _add(catalog, "Dune Messiah")
        _add(catalog, "Children of Dune")  # "Dune" not a prefix here
        cid = catalog.create_collection("Dune-prefixed", query="title:Dune*")
        assert sorted(catalog.resolve_collection_member_ids(cid)) == sorted([d1, d2])

    def test_publisher_equality(self, catalog: LibraryCatalog) -> None:
        t = _add(catalog, "Hyperion", publisher="Tor")
        _add(catalog, "Other", publisher="Ace")
        cid = catalog.create_collection("Tor", query="publisher:Tor")
        assert catalog.resolve_collection_member_ids(cid) == [t]

    def test_language_equality(self, catalog: LibraryCatalog) -> None:
        en = _add(catalog, "English Book", language="en")
        _add(catalog, "French Book", language="fr")
        cid = catalog.create_collection("English", query="language:en")
        assert catalog.resolve_collection_member_ids(cid) == [en]

    def test_isbn_equality(self, catalog: LibraryCatalog) -> None:
        target = _add(catalog, "ISBN Book", isbn="9780441013593")
        _add(catalog, "Other ISBN", isbn="9780553283686")
        cid = catalog.create_collection("ByISBN", query="isbn:9780441013593")
        assert catalog.resolve_collection_member_ids(cid) == [target]

    def test_tag_membership(self, catalog: LibraryCatalog) -> None:
        f1 = _add(catalog, "Fav One", tag="favorites")
        _add(catalog, "Meh", tag="meh")
        cid = catalog.create_collection("Favs", query="tag:favorites")
        assert catalog.resolve_collection_member_ids(cid) == [f1]

    def test_id_equality(self, catalog: LibraryCatalog) -> None:
        a = _add(catalog, "A")
        _add(catalog, "B")
        cid = catalog.create_collection("ById", query=f"id:{a}")
        assert catalog.resolve_collection_member_ids(cid) == [a]

    def test_like_metacharacters_match_literally(self, catalog: LibraryCatalog) -> None:
        # A literal '%' in the value must not become a wildcard.
        match = _add(catalog, "Pct", authors=["50% Off"])
        _add(catalog, "NoPct", authors=["Frank Herbert"])
        cid = catalog.create_collection("Pct", query='author:"50% Off"')
        assert catalog.resolve_collection_member_ids(cid) == [match]


class TestRangeAndComparisonRules:
    def test_year_inclusive_range(self, catalog: LibraryCatalog) -> None:
        old = _add(catalog, "Old", published_date="1999-06-01")
        lo = _add(catalog, "Lo", published_date="2000-01-01")
        mid = _add(catalog, "Mid", published_date="2005-03-03")
        hi = _add(catalog, "Hi", published_date="2010-12-31")
        _add(catalog, "Future", published_date="2011-01-01")
        cid = catalog.create_collection("00s", query="year:[2000 TO 2010]")
        assert sorted(catalog.resolve_collection_member_ids(cid)) == sorted([lo, mid, hi])
        assert old not in catalog.resolve_collection_member_ids(cid)

    def test_year_exclusive_range_drops_endpoints(self, catalog: LibraryCatalog) -> None:
        _add(catalog, "Lo", published_date="2000-01-01")
        mid = _add(catalog, "Mid", published_date="2005-03-03")
        _add(catalog, "Hi", published_date="2010-12-31")
        cid = catalog.create_collection("strict", query="year:{2000 TO 2010}")
        assert catalog.resolve_collection_member_ids(cid) == [mid]

    def test_year_open_upper_bound(self, catalog: LibraryCatalog) -> None:
        _add(catalog, "Old", published_date="2019-01-01")
        new1 = _add(catalog, "New1", published_date="2020-01-01")
        new2 = _add(catalog, "New2", published_date="2024-06-01")
        cid = catalog.create_collection("2020+", query="year:[2020 TO *]")
        assert sorted(catalog.resolve_collection_member_ids(cid)) == sorted([new1, new2])

    def test_year_equality(self, catalog: LibraryCatalog) -> None:
        match = _add(catalog, "Y2020", published_date="2020-07-07")
        _add(catalog, "Y2019", published_date="2019-07-07")
        cid = catalog.create_collection("Just2020", query="year:2020")
        assert catalog.resolve_collection_member_ids(cid) == [match]

    def test_rating_ge_comparison(self, catalog: LibraryCatalog) -> None:
        good = _add(catalog, "Good", rating=4.5)
        edge = _add(catalog, "Edge", rating=4.0)
        _add(catalog, "Meh", rating=3.0)
        cid = catalog.create_collection("Top", query="rating:>=4")
        assert sorted(catalog.resolve_collection_member_ids(cid)) == sorted([good, edge])

    def test_rating_gt_excludes_boundary(self, catalog: LibraryCatalog) -> None:
        good = _add(catalog, "Good", rating=4.5)
        _add(catalog, "Edge", rating=4.0)
        cid = catalog.create_collection("AboveFour", query="rating:>4")
        assert catalog.resolve_collection_member_ids(cid) == [good]

    def test_added_date_range(self, catalog: LibraryCatalog) -> None:
        before = _add(catalog, "Before", date_added="2023-12-31T10:00:00")
        within = _add(catalog, "Within", date_added="2024-06-15T08:30:00")
        on_end = _add(catalog, "OnEnd", date_added="2024-12-31T23:59:59")
        _add(catalog, "After", date_added="2025-01-02T00:00:00")
        cid = catalog.create_collection("2024", query="added:[2024-01-01 TO 2024-12-31]")
        members = sorted(catalog.resolve_collection_member_ids(cid))
        # Day-granularity: a timestamp late on the end date is still included.
        assert members == sorted([within, on_end])
        assert before not in members


class TestBooleanRules:
    def test_and_intersects(self, catalog: LibraryCatalog) -> None:
        match = _add(catalog, "Dune", genre="Science Fiction", authors=["Frank Herbert"])
        _add(catalog, "Neuromancer", genre="Science Fiction", authors=["William Gibson"])
        _add(catalog, "Hellstrom", genre="Horror", authors=["Frank Herbert"])
        cid = catalog.create_collection(
            "SF Herbert", query='genre:"Science Fiction" AND author:Herbert'
        )
        assert catalog.resolve_collection_member_ids(cid) == [match]

    def test_or_unions(self, catalog: LibraryCatalog) -> None:
        t = _add(catalog, "Hobbit", authors=["J.R.R. Tolkien"])
        lewis = _add(catalog, "Narnia", authors=["C.S. Lewis"])
        _add(catalog, "Dune", authors=["Frank Herbert"])
        cid = catalog.create_collection("Inklings", query="author:Tolkien OR author:Lewis")
        assert sorted(catalog.resolve_collection_member_ids(cid)) == sorted([t, lewis])

    def test_and_not_excludes(self, catalog: LibraryCatalog) -> None:
        keep = _add(catalog, "Fresh Fantasy", genre="Fantasy")
        _add(catalog, "Old Favorite", genre="Fantasy", tag="reread")
        cid = catalog.create_collection("Unread Fantasy", query="genre:Fantasy NOT tag:reread")
        assert catalog.resolve_collection_member_ids(cid) == [keep]

    def test_top_level_not_returns_complement(self, catalog: LibraryCatalog) -> None:
        _add(catalog, "Scary", genre="Horror")
        fantasy = _add(catalog, "Friendly", genre="Fantasy")
        plain = _add(catalog, "Plain")  # no genre at all
        cid = catalog.create_collection("Not Horror", query="NOT genre:Horror")
        members = catalog.resolve_collection_member_ids(cid)
        assert set(members) == {fantasy, plain}

    def test_grouping_controls_precedence(self, catalog: LibraryCatalog) -> None:
        recent_t = _add(
            catalog, "New Tolkien", authors=["J.R.R. Tolkien"], published_date="2021-01-01"
        )
        _add(catalog, "Old Lewis", authors=["C.S. Lewis"], published_date="2019-01-01")
        _add(catalog, "New Herbert", authors=["Frank Herbert"], published_date="2022-01-01")
        cid = catalog.create_collection(
            "Recent Inklings",
            query="(author:Tolkien OR author:Lewis) AND year:[2020 TO *]",
        )
        assert catalog.resolve_collection_member_ids(cid) == [recent_t]


class TestPreviewQuery:
    def test_preview_returns_records_without_saving(self, catalog: LibraryCatalog) -> None:
        _add(catalog, "SF One", genre="Science Fiction")
        before = len(catalog.list_collections())
        records = catalog.preview_query('genre:"Science Fiction"')
        assert len(records) == 1
        assert len(catalog.list_collections()) == before  # nothing persisted

    def test_preview_invalid_query_raises(self, catalog: LibraryCatalog) -> None:
        with pytest.raises(CollectionQueryError):
            catalog.preview_query("nonsense:Tor")


class TestResolveQueryPreview:
    """Ad-hoc query preview: (true_total, capped_sample) without persisting (#253)."""

    def test_returns_total_and_ordered_sample(self, catalog: LibraryCatalog) -> None:
        _add(catalog, "The Border", genre="Science Fiction")  # title_sort "Border"
        _add(catalog, "Apex", genre="Science Fiction")
        total, sample = catalog.resolve_query_preview('genre:"Science Fiction"', limit=50)
        assert total == 2
        assert [r.metadata.title for r in sample] == ["Apex", "The Border"]

    def test_caps_sample_but_reports_true_total(self, catalog: LibraryCatalog) -> None:
        for i in range(5):
            _add(catalog, f"Book {i}", genre="Science Fiction")
        total, sample = catalog.resolve_query_preview('genre:"Science Fiction"', limit=2)
        assert total == 5
        assert len(sample) == 2
        # Cap is applied after title_sort ordering, so it's the first 2.
        assert [r.metadata.title for r in sample] == ["Book 0", "Book 1"]

    def test_invalid_query_raises(self, catalog: LibraryCatalog) -> None:
        with pytest.raises(CollectionQueryError):
            catalog.resolve_query_preview("nonsense:Tor", limit=50)

    def test_zero_match_returns_zero_and_empty(self, catalog: LibraryCatalog) -> None:
        _add(catalog, "A Fantasy", genre="Fantasy")
        total, sample = catalog.resolve_query_preview('genre:"Science Fiction"', limit=50)
        assert total == 0
        assert sample == []

    def test_does_not_persist(self, catalog: LibraryCatalog) -> None:
        _add(catalog, "SF One", genre="Science Fiction")
        before = len(catalog.list_collections())
        catalog.resolve_query_preview('genre:"Science Fiction"', limit=50)
        assert len(catalog.list_collections()) == before


class TestConversion:
    def test_set_query_converts_static_to_rule_and_clears_rows(
        self, catalog: LibraryCatalog
    ) -> None:
        manual = _add(catalog, "Manual Pick")
        sf = _add(catalog, "SF One", genre="Science Fiction")
        cid = catalog.create_collection("Mixed")
        catalog.add_books_to_collection(cid, [manual])

        catalog.set_collection_query(cid, 'genre:"Science Fiction"')

        assert _query_of(catalog, cid) == 'genre:"Science Fiction"'
        # Static rows are dropped — a rule-based collection holds zero of them.
        rows = catalog._conn.execute(
            "SELECT book_id FROM collection_books WHERE collection_id = ?", (cid,)
        ).fetchall()
        assert rows == []
        assert catalog.resolve_collection_member_ids(cid) == [sf]

    def test_clear_query_snapshots_members_into_static(self, catalog: LibraryCatalog) -> None:
        sf1 = _add(catalog, "SF One", genre="Science Fiction")
        sf2 = _add(catalog, "SF Two", genre="Science Fiction")
        cid = catalog.create_collection("Sci-Fi", query='genre:"Science Fiction"')

        catalog.clear_collection_query(cid)

        assert _query_of(catalog, cid) is None
        snapshot = {
            row["book_id"]
            for row in catalog._conn.execute(
                "SELECT book_id FROM collection_books WHERE collection_id = ?", (cid,)
            )
        }
        assert snapshot == {sf1, sf2}
        assert sorted(catalog.resolve_collection_member_ids(cid)) == sorted([sf1, sf2])

    def test_set_invalid_query_raises_and_does_not_persist(self, catalog: LibraryCatalog) -> None:
        cid = catalog.create_collection("X")
        with pytest.raises(CollectionQueryError):
            catalog.set_collection_query(cid, "nonsense:Tor")
        assert _query_of(catalog, cid) is None


class TestListCollectionsLiveCount:
    def test_rule_based_count_is_live(self, catalog: LibraryCatalog) -> None:
        _add(catalog, "SF One", genre="Science Fiction")
        _add(catalog, "SF Two", genre="Science Fiction")
        catalog.create_collection("Sci-Fi", query='genre:"Science Fiction"')
        row = next(c for c in catalog.list_collections() if c["name"] == "Sci-Fi")
        assert row["book_count"] == 2
