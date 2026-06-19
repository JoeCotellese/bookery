# ABOUTME: Integration tests for catalog author dedupe reads + rewrite_author.
# ABOUTME: Drives real SQLite I/O: clusters, co-author safety, idempotence (#261).

from pathlib import Path

import pytest

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata import BookMetadata


@pytest.fixture
def catalog(tmp_path: Path) -> LibraryCatalog:
    conn = open_library(tmp_path / "lib.db")
    return LibraryCatalog(conn)


def _add(catalog: LibraryCatalog, title: str, authors: list[str]) -> int:
    return catalog.add_book(
        BookMetadata(title=title, authors=authors, source_path=Path(f"/src/{title}.epub")),
        file_hash=f"hash-{title}",
    )


class TestAuthorForms:
    def test_maps_each_distinct_spelling_to_book_ids(self, catalog: LibraryCatalog) -> None:
        a = _add(catalog, "Raise the Titanic", ["Cussler, Clive"])
        b = _add(catalog, "Sahara", ["Clive Cussler"])
        c = _add(catalog, "Crescent Dawn", ["Clive Cussler", "Dirk Cussler"])

        forms = catalog.author_forms()

        assert forms["Cussler, Clive"] == [a]
        assert sorted(forms["Clive Cussler"]) == sorted([b, c])
        assert forms["Dirk Cussler"] == [c]


class TestAuthorClusters:
    def test_groups_spellings_of_one_author(self, catalog: LibraryCatalog) -> None:
        _add(catalog, "Raise the Titanic", ["Cussler, Clive"])
        _add(catalog, "Sahara", ["Clive Cussler"])

        clusters = catalog.author_clusters()

        assert len(clusters) == 1
        names = {form.name for form in clusters[0].forms}
        assert names == {"Cussler, Clive", "Clive Cussler"}

    def test_excludes_single_form_authors(self, catalog: LibraryCatalog) -> None:
        _add(catalog, "Solo Work", ["Brandon Sanderson"])

        assert catalog.author_clusters() == []

    def test_son_is_not_clustered_with_father(self, catalog: LibraryCatalog) -> None:
        _add(catalog, "Raise the Titanic", ["Cussler, Clive"])
        _add(catalog, "Sahara", ["Clive Cussler"])
        _add(catalog, "The Navigator", ["Dirk Cussler"])

        clusters = catalog.author_clusters()
        all_names = {f.name for c in clusters for f in c.forms}

        assert "Dirk Cussler" not in all_names


class TestRewriteAuthor:
    def test_rewrites_matching_books_and_returns_count(self, catalog: LibraryCatalog) -> None:
        a = _add(catalog, "Raise the Titanic", ["Cussler, Clive"])
        _add(catalog, "Unrelated", ["Brandon Sanderson"])

        changed = catalog.rewrite_author("Cussler, Clive", "Clive Cussler")

        assert changed == 1
        rec = catalog.get_by_id(a)
        assert rec is not None
        assert rec.metadata.authors == ["Clive Cussler"]

    def test_coauthors_left_intact(self, catalog: LibraryCatalog) -> None:
        book = _add(catalog, "Crescent Dawn", ["Cussler, Clive", "Dirk Cussler"])

        catalog.rewrite_author("Cussler, Clive", "Clive Cussler")

        rec = catalog.get_by_id(book)
        assert rec is not None
        assert rec.metadata.authors == ["Clive Cussler", "Dirk Cussler"]

    def test_dedupes_when_target_already_present(self, catalog: LibraryCatalog) -> None:
        book = _add(catalog, "Odd Edit", ["Cussler, Clive", "Clive Cussler"])

        catalog.rewrite_author("Cussler, Clive", "Clive Cussler")

        rec = catalog.get_by_id(book)
        assert rec is not None
        assert rec.metadata.authors == ["Clive Cussler"]

    def test_is_idempotent(self, catalog: LibraryCatalog) -> None:
        _add(catalog, "Raise the Titanic", ["Cussler, Clive"])

        first = catalog.rewrite_author("Cussler, Clive", "Clive Cussler")
        second = catalog.rewrite_author("Cussler, Clive", "Clive Cussler")

        assert first == 1
        assert second == 0

    def test_recomputes_author_sort(self, catalog: LibraryCatalog) -> None:
        book = _add(catalog, "Raise the Titanic", ["Cussler, Clive"])

        catalog.rewrite_author("Cussler, Clive", "Clive Cussler")

        row = catalog._conn.execute(
            "SELECT author_sort FROM books WHERE id = ?", (book,)
        ).fetchone()
        assert row["author_sort"] == "Cussler, Clive"
