# ABOUTME: Tests for the /series index and /series/<name> detail pages (#297).
# ABOUTME: Covers listing, ordering, 404s, slash-in-name routing, and index formatting.

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
