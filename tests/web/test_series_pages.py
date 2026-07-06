# ABOUTME: Tests for the /series index and /series/<name> detail pages (#297).
# ABOUTME: Covers listing, ordering, 404s, slash-in-name routing, and index formatting.

import re

from bookery.db.catalog import SeriesSummary
from tests.web.conftest import make_book


class TestSeriesIndexPage:
    def test_lists_series_with_counts(self, mock_catalog, client):
        mock_catalog.list_series.return_value = [
            SeriesSummary(series="Dune", book_count=6, missing_index_count=0),
            SeriesSummary(series="The Wheel of Time", book_count=14, missing_index_count=3),
        ]

        response = client.get("/series")

        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "Dune" in html
        assert "The Wheel of Time" in html
        assert "6" in html
        assert "14" in html

    def test_series_names_link_to_detail(self, mock_catalog, client):
        mock_catalog.list_series.return_value = [
            SeriesSummary(series="Dune", book_count=6, missing_index_count=0),
        ]

        html = client.get("/series").get_data(as_text=True)

        assert 'href="/series/Dune"' in html

    def test_missing_position_hint_shown(self, mock_catalog, client):
        mock_catalog.list_series.return_value = [
            SeriesSummary(series="Dune", book_count=6, missing_index_count=2),
        ]

        html = client.get("/series").get_data(as_text=True)

        assert "2 missing" in html

    def test_empty_state_mentions_backfill(self, mock_catalog, client):
        mock_catalog.list_series.return_value = []

        html = client.get("/series").get_data(as_text=True)

        assert "series backfill" in html


class TestSeriesNav:
    def test_masthead_has_series_link_with_count(self, mock_catalog, client):
        mock_catalog.count_series.return_value = 7

        html = client.get("/series").get_data(as_text=True)

        match = re.search(
            r'<a href="/series"[^>]*>\s*Series\s*<span class="nav-count">7</span>', html
        )
        assert match, "masthead should link to /series with the series count"

    def test_series_nav_active_on_series_pages(self, mock_catalog, client):
        html = client.get("/series").get_data(as_text=True)

        assert re.search(r'<a href="/series"[^>]*aria-current="page"', html)
        assert not re.search(r'<a href="/books"[^>]*aria-current="page"', html)

    def test_books_nav_still_active_on_books_page(self, mock_catalog, client):
        html = client.get("/books").get_data(as_text=True)

        assert re.search(r'<a href="/books"[^>]*aria-current="page"', html)
        assert not re.search(r'<a href="/series"[^>]*aria-current="page"', html)


class TestSeriesDetailPage:
    def test_books_render_in_given_order_with_positions(self, mock_catalog, client):
        mock_catalog.list_by_series.return_value = [
            make_book(1, title="Book One", authors=["A. Writer"], series="Dune", series_index=1.0),
            make_book(2, title="Book Two", authors=["A. Writer"], series="Dune", series_index=2.0),
        ]

        response = client.get("/series/Dune")

        assert response.status_code == 200
        mock_catalog.list_by_series.assert_called_once_with("Dune")
        html = response.get_data(as_text=True)
        assert html.index("Book One") < html.index("Book Two")
        assert 'href="/books/1"' in html

    def test_whole_number_index_renders_without_decimal(self, mock_catalog, client):
        mock_catalog.list_by_series.return_value = [
            make_book(1, title="Book One", series="Dune", series_index=1.0),
        ]

        html = client.get("/series/Dune").get_data(as_text=True)

        assert "#1" in html
        assert "#1.0" not in html

    def test_fractional_index_keeps_fraction(self, mock_catalog, client):
        mock_catalog.list_by_series.return_value = [
            make_book(1, title="Novella", series="Dune", series_index=1.5),
        ]

        html = client.get("/series/Dune").get_data(as_text=True)

        assert "#1.5" in html

    def test_book_without_index_renders_without_position(self, mock_catalog, client):
        mock_catalog.list_by_series.return_value = [
            make_book(1, title="Uncharted", series="Dune", series_index=None),
        ]

        response = client.get("/series/Dune")

        assert response.status_code == 200
        assert "#" not in response.get_data(as_text=True).split("Uncharted")[1].split("</li>")[0]

    def test_unknown_series_404s(self, mock_catalog, client):
        mock_catalog.list_by_series.return_value = []

        assert client.get("/series/Nope").status_code == 404

    def test_series_name_with_slash_routes(self, mock_catalog, client):
        mock_catalog.list_by_series.return_value = [
            make_book(1, title="Odd One", series="Fafhrd/Mouser", series_index=1.0),
        ]

        response = client.get("/series/Fafhrd/Mouser")

        assert response.status_code == 200
        mock_catalog.list_by_series.assert_called_once_with("Fafhrd/Mouser")


class TestBookListSeriesColumn:
    """#297 — toggleable, sortable Series column on /books."""

    def _seed(self, mock_catalog, series: str | None = "Dune", series_index: float | None = 1.0):
        book = make_book(1, series=series, series_index=series_index)
        mock_catalog.browse.return_value = ([book], 1)

    def test_hidden_by_default(self, mock_catalog, client):
        self._seed(mock_catalog)

        html = client.get("/books").data.decode()

        assert 'class="col-series"' not in html

    def test_toggled_on_renders_name_and_position(self, mock_catalog, client):
        self._seed(mock_catalog)
        client.set_cookie("book_columns", "series")

        html = client.get("/books").data.decode()

        assert 'class="col-series"' in html
        assert "Dune #1" in html

    def test_header_is_a_sort_link(self, mock_catalog, client):
        self._seed(mock_catalog)
        client.set_cookie("book_columns", "series")

        html = client.get("/books").data.decode()

        assert "sort=series" in html

    def test_book_without_series_renders_empty_cell(self, mock_catalog, client):
        self._seed(mock_catalog, series=None, series_index=None)
        client.set_cookie("book_columns", "series")

        html = client.get("/books").data.decode()

        assert 'class="col-series"' in html

    def test_sort_series_forwards_to_catalog_browse(self, mock_catalog, client):
        mock_catalog.browse.return_value = ([], 0)

        client.get("/books?sort=series")

        assert mock_catalog.browse.call_args.kwargs["sort"] == "series"
