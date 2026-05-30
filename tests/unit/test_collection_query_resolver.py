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
) -> int:
    book_id = catalog.add_book(
        BookMetadata(title=title, series=series, source_path=Path(f"/books/{title}.epub")),
        file_hash=f"hash_{title}",
    )
    if genre is not None:
        catalog.add_genre(book_id, genre, is_primary=True)
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


class TestPreviewQuery:
    def test_preview_returns_records_without_saving(self, catalog: LibraryCatalog) -> None:
        _add(catalog, "SF One", genre="Science Fiction")
        before = len(catalog.list_collections())
        records = catalog.preview_query('genre:"Science Fiction"')
        assert len(records) == 1
        assert len(catalog.list_collections()) == before  # nothing persisted

    def test_preview_invalid_query_raises(self, catalog: LibraryCatalog) -> None:
        with pytest.raises(CollectionQueryError):
            catalog.preview_query("publisher:Tor")


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

    def test_set_invalid_query_raises_and_does_not_persist(
        self, catalog: LibraryCatalog
    ) -> None:
        cid = catalog.create_collection("X")
        with pytest.raises(CollectionQueryError):
            catalog.set_collection_query(cid, "publisher:Tor")
        assert _query_of(catalog, cid) is None


class TestListCollectionsLiveCount:
    def test_rule_based_count_is_live(self, catalog: LibraryCatalog) -> None:
        _add(catalog, "SF One", genre="Science Fiction")
        _add(catalog, "SF Two", genre="Science Fiction")
        catalog.create_collection("Sci-Fi", query='genre:"Science Fiction"')
        row = next(c for c in catalog.list_collections() if c["name"] == "Sci-Fi")
        assert row["book_count"] == 2
