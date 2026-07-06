# ABOUTME: E2E walk of the #297 series browsing surface on a real catalog.
# ABOUTME: /series index -> series detail -> book detail "# N of M" -> sorted /books column.

from pathlib import Path

import pytest

from bookery.db.catalog import LibraryCatalog
from bookery.db.connection import open_library
from bookery.metadata.types import BookMetadata
from bookery.web import create_app


@pytest.fixture()
def catalog(tmp_path: Path) -> LibraryCatalog:
    """A real catalog: one 4-book series (one book unpositioned) + a standalone."""
    conn = open_library(tmp_path / "series_e2e.db")
    catalog = LibraryCatalog(conn)
    books = [
        ("The Eye of the World", "The Wheel of Time", 1.0),
        ("The Great Hunt", "The Wheel of Time", 2.0),
        ("The Dragon Reborn", "The Wheel of Time", 3.0),
        ("New Spring", "The Wheel of Time", None),
        ("Standalone Novel", None, None),
    ]
    for i, (title, series, index) in enumerate(books):
        catalog.add_book(
            BookMetadata(
                title=title,
                authors=["Robert Jordan"],
                series=series,
                series_index=index,
                source_path=Path(f"/books/{i}.epub"),
            ),
            file_hash=f"hash{i}",
        )
    return catalog


@pytest.fixture()
def client(catalog: LibraryCatalog):
    app = create_app(catalog)
    app.config["TESTING"] = True
    return app.test_client()


class TestSeriesBrowsingEndToEnd:
    def test_index_lists_series_with_count_and_nav_shows_it(self, client) -> None:
        html = client.get("/series").get_data(as_text=True)

        assert "The Wheel of Time" in html
        assert "4" in html
        assert "1 missing position" in html
        assert "Standalone Novel" not in html
        # Masthead count reflects the one distinct series.
        assert '<span class="nav-count">1</span>' in html

    def test_detail_orders_by_position_with_unknowns_last(self, client) -> None:
        html = client.get("/series/The Wheel of Time").get_data(as_text=True)

        eye = html.index("The Eye of the World")
        hunt = html.index("The Great Hunt")
        dragon = html.index("The Dragon Reborn")
        spring = html.index("New Spring")
        assert eye < hunt < dragon < spring
        assert "#1" in html
        assert "4 books" in html

    def test_book_detail_shows_position_of_total_linking_back(self, client) -> None:
        # Book ids are insertion-ordered; book 1 is The Eye of the World.
        html = client.get("/books/1").get_data(as_text=True)

        assert "#1 of 4" in html
        assert 'href="/series/The%20Wheel%20of%20Time"' in html

    def test_unknown_series_404s(self, client) -> None:
        assert client.get("/series/Malazan").status_code == 404

    def test_books_sorted_by_series_with_column_visible(self, client) -> None:
        html = client.get("/books?sort=series&cols_set=1&cols=series").get_data(as_text=True)

        assert 'class="col-series"' in html
        assert "The Wheel of Time #1" in html
        # Unseriesed books sink to the bottom on the default ascending sort.
        eye = html.index("The Eye of the World")
        standalone = html.index("Standalone Novel")
        assert eye < standalone
