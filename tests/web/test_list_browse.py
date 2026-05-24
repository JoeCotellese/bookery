# ABOUTME: Plan-01 list browse surface tests — BrowseQuery, pagination, count label.
# ABOUTME: Covers the cells of the test matrix that exist after PR 1 (steps 1+2 of plan-01).

import pytest

from bookery.web.browse import (
    DEFAULT_PAGE_SIZE,
    BrowsePage,
    BrowseQuery,
    from_request_args,
)

from .conftest import make_book

# --- BrowseQuery parsing ---


class TestBrowseQueryParsing:
    def test_defaults_when_args_empty(self):
        q = from_request_args({})
        assert q.q == ""
        assert q.page == 1
        assert q.page_size == DEFAULT_PAGE_SIZE
        assert q.offset == 0

    def test_parses_q_and_page(self):
        q = from_request_args({"q": "dune", "page": "3"})
        assert q.q == "dune"
        assert q.page == 3
        assert q.offset == 2 * DEFAULT_PAGE_SIZE

    def test_strips_whitespace_in_q(self):
        q = from_request_args({"q": "  dune  "})
        assert q.q == "dune"

    @pytest.mark.parametrize("bad", ["0", "-5", "abc", "", "1.5"])
    def test_invalid_page_clamps_to_one(self, bad):
        q = from_request_args({"page": bad})
        assert q.page == 1

    def test_custom_default_page_size(self):
        q = from_request_args({}, default_page_size=10)
        assert q.page_size == 10


# --- BrowsePage derivations ---


class TestBrowsePageDerivations:
    def _page(self, total: int, page: int, page_size: int = 50) -> BrowsePage:
        return BrowsePage(
            books=[],
            total=total,
            page=page,
            page_size=page_size,
            query=BrowseQuery(page=page, page_size=page_size),
        )

    def test_start_end_for_first_page(self):
        p = self._page(total=120, page=1)
        assert (p.start, p.end) == (1, 50)

    def test_start_end_for_middle_page(self):
        p = self._page(total=120, page=2)
        assert (p.start, p.end) == (51, 100)

    def test_end_clamps_to_total_on_last_page(self):
        p = self._page(total=120, page=3)
        assert (p.start, p.end) == (101, 120)

    def test_empty_results_zero_bounds(self):
        p = self._page(total=0, page=1)
        assert (p.start, p.end) == (0, 0)

    def test_total_pages_rounds_up(self):
        assert self._page(total=120, page=1).total_pages == 3
        assert self._page(total=100, page=1).total_pages == 2
        assert self._page(total=1, page=1).total_pages == 1
        assert self._page(total=0, page=1).total_pages == 1

    def test_has_prev_next(self):
        first = self._page(total=120, page=1)
        middle = self._page(total=120, page=2)
        last = self._page(total=120, page=3)
        assert first.has_prev is False and first.has_next is True
        assert middle.has_prev is True and middle.has_next is True
        assert last.has_prev is True and last.has_next is False


# --- /books route: pagination + count ---


def _stub_browse(mock_catalog, *, books, total):
    """Wire ``mock_catalog.browse`` to return the supplied books + total."""
    mock_catalog.browse.return_value = (books, total)


class TestBooksRoutePagination:
    def test_route_calls_catalog_browse_with_parsed_query(self, mock_catalog, client):
        _stub_browse(mock_catalog, books=[], total=0)

        client.get("/books?q=dune&page=2")

        mock_catalog.browse.assert_called_once()
        kwargs = mock_catalog.browse.call_args.kwargs
        assert kwargs["q"] == "dune"
        assert kwargs["offset"] == DEFAULT_PAGE_SIZE
        assert kwargs["limit"] == DEFAULT_PAGE_SIZE

    def test_route_renders_only_one_page_of_results(self, mock_catalog, client):
        books = [make_book(i, title=f"Book {i:03d}") for i in range(1, 51)]
        _stub_browse(mock_catalog, books=books, total=120)

        response = client.get("/books")
        html = response.data.decode()
        assert "Book 001" in html
        assert "Book 050" in html
        # Catalog was asked for 50 rows — anything beyond is the catalog's concern.
        kwargs = mock_catalog.browse.call_args.kwargs
        assert kwargs["limit"] == 50

    def test_route_renders_count_label(self, mock_catalog, client):
        books = [make_book(i) for i in range(51, 101)]
        _stub_browse(mock_catalog, books=books, total=120)

        response = client.get("/books?page=2")
        html = response.data.decode()
        # Use the en-dash form rendered in the template
        assert "Showing 51&ndash;100 of 120" in html

    def test_route_renders_empty_count_when_no_results(self, mock_catalog, client):
        _stub_browse(mock_catalog, books=[], total=0)

        response = client.get("/books")
        html = response.data.decode()
        assert "Your library is empty" in html
        # No "Showing X of Y" label when there is nothing to show.
        assert "Showing" not in html

    def test_route_clamps_out_of_range_page(self, mock_catalog, client):
        books = [make_book(i) for i in range(1, 21)]

        def fake_browse(*, q: str, offset: int, limit: int):
            del q, limit
            # First call: probe with the requested (out of range) offset returns
            # empty plus the real total. Route then re-queries with the clamped
            # offset and we return the actual books.
            return (books if offset == 0 else [], len(books))

        mock_catalog.browse.side_effect = fake_browse

        response = client.get("/books?page=99")
        assert response.status_code == 200
        html = response.data.decode()
        # Page label reflects the clamped page (1, since 20 < 50)
        assert "Showing 1&ndash;20 of 20" in html

    def test_pager_links_preserve_search_query(self, mock_catalog, client):
        books = [make_book(i) for i in range(1, 51)]
        _stub_browse(mock_catalog, books=books, total=120)

        response = client.get("/books?q=dune&page=2")
        html = response.data.decode()
        # Both prev and next should carry q=dune
        assert "q=dune" in html
        assert "page=1" in html
        assert "page=3" in html

    def test_no_pager_when_results_fit_one_page(self, mock_catalog, client):
        books = [make_book(i) for i in range(1, 11)]
        _stub_browse(mock_catalog, books=books, total=10)

        response = client.get("/books")
        html = response.data.decode()
        # No nav pager rendered
        assert 'class="pager"' not in html

    def test_htmx_request_returns_partial_with_count_and_rows(self, mock_catalog, client):
        books = [make_book(1, title="Solo Book")]
        _stub_browse(mock_catalog, books=books, total=1)

        response = client.get("/books", headers={"HX-Request": "true"})
        html = response.data.decode()
        assert "<html" not in html
        assert "Solo Book" in html
        assert "Showing 1&ndash;1 of 1" in html
