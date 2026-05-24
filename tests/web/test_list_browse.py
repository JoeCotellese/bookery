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


# --- BrowseQuery sort/dir parsing ---


class TestBrowseQuerySortParsing:
    def test_defaults_to_author_asc(self):
        # Default matches the pre-sortable behavior of the list controller
        # (author_sort, title ascending) so an unbookmarked /books visit
        # renders the same order users were already used to.
        q = from_request_args({})
        assert q.sort == "author"
        assert q.dir == "asc"

    @pytest.mark.parametrize("key", ["title", "author", "added"])
    def test_parses_allowed_sort_keys(self, key):
        q = from_request_args({"sort": key})
        assert q.sort == key

    @pytest.mark.parametrize("direction", ["asc", "desc"])
    def test_parses_allowed_directions(self, direction):
        q = from_request_args({"sort": "title", "dir": direction})
        assert q.dir == direction

    @pytest.mark.parametrize("bad_sort", ["bogus", "id", "", "TITLE", "author;drop"])
    def test_unknown_sort_falls_back_to_default(self, bad_sort):
        q = from_request_args({"sort": bad_sort})
        assert q.sort == "author"

    @pytest.mark.parametrize("bad_dir", ["sideways", "", "ASC", "DESC", "ascending"])
    def test_unknown_dir_falls_back_to_asc(self, bad_dir):
        q = from_request_args({"sort": "title", "dir": bad_dir})
        assert q.dir == "asc"

    def test_with_page_preserves_sort_and_dir(self):
        q = from_request_args({"sort": "author", "dir": "desc", "page": "3"})
        bumped = q.with_page(5)
        assert bumped.sort == "author"
        assert bumped.dir == "desc"
        assert bumped.page == 5


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

        def fake_browse(*, q: str, offset: int, limit: int, sort: str = "", dir: str = ""):
            del q, limit, sort, dir
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


# --- /books route: sortable columns ---


class TestBooksRouteSort:
    def test_route_passes_sort_and_dir_to_catalog(self, mock_catalog, client):
        _stub_browse(mock_catalog, books=[], total=0)

        client.get("/books?sort=author&dir=desc")

        kwargs = mock_catalog.browse.call_args.kwargs
        assert kwargs["sort"] == "author"
        assert kwargs["dir"] == "desc"

    def test_route_defaults_to_author_asc(self, mock_catalog, client):
        _stub_browse(mock_catalog, books=[], total=0)

        client.get("/books")

        kwargs = mock_catalog.browse.call_args.kwargs
        assert kwargs["sort"] == "author"
        assert kwargs["dir"] == "asc"

    def test_route_silently_ignores_unknown_sort(self, mock_catalog, client):
        _stub_browse(mock_catalog, books=[], total=0)

        response = client.get("/books?sort=bogus&dir=sideways")

        assert response.status_code == 200
        kwargs = mock_catalog.browse.call_args.kwargs
        assert kwargs["sort"] == "author"
        assert kwargs["dir"] == "asc"

    def test_active_column_has_descending_chevron(self, mock_catalog, client):
        # Matrix row: 1280px, sort=author dir=desc → first row matches expected,
        # chevron on header.
        books = [
            make_book(1, title="Zeppelin", authors=["Zelda"]),
            make_book(2, title="Apple", authors=["Adams"]),
        ]
        _stub_browse(mock_catalog, books=books, total=2)

        response = client.get("/books?sort=author&dir=desc")
        html = response.data.decode()

        # Chevron on the active Author header — descending arrow.
        assert "Author" in html
        assert "▼" in html or "&#9660;" in html or "▼" in html
        # First rendered row matches the order the catalog returned.
        first_row_idx = html.find("Zeppelin")
        second_row_idx = html.find("Apple")
        assert first_row_idx != -1 and second_row_idx != -1
        assert first_row_idx < second_row_idx

    def test_inactive_columns_have_no_chevron(self, mock_catalog, client):
        _stub_browse(mock_catalog, books=[make_book(1)], total=1)

        response = client.get("/books?sort=title&dir=asc")
        html = response.data.decode()
        # Active column shows ascending chevron. Match the HTML entity the
        # template emits as well as the literal glyph in case either form
        # is in use.
        assert "▲" in html or "&#9650;" in html
        # Inactive columns must not carry the chevron — exactly one chevron
        # appears in the rendered headers.
        chevron_count = (
            html.count("▲") + html.count("▼") + html.count("&#9650;") + html.count("&#9660;")
        )
        assert chevron_count == 1

    def test_header_link_toggles_direction_when_active(self, mock_catalog, client):
        _stub_browse(mock_catalog, books=[make_book(1)], total=1)

        response = client.get("/books?sort=title&dir=asc")
        html = response.data.decode()
        # Clicking the active title header again should flip to desc.
        assert "sort=title&amp;dir=desc" in html or "sort=title&dir=desc" in html

    def test_header_link_uses_asc_for_inactive_columns(self, mock_catalog, client):
        _stub_browse(mock_catalog, books=[make_book(1)], total=1)

        response = client.get("/books?sort=title&dir=asc")
        html = response.data.decode()
        # Inactive Author header defaults to asc on first click.
        assert "sort=author&amp;dir=asc" in html or "sort=author&dir=asc" in html
        assert "sort=added&amp;dir=asc" in html or "sort=added&dir=asc" in html

    def test_header_link_resets_page_to_one_on_sort_change(self, mock_catalog, client):
        books = [make_book(i) for i in range(1, 51)]
        _stub_browse(mock_catalog, books=books, total=120)

        response = client.get("/books?page=3&sort=title&dir=asc")
        html = response.data.decode()
        # Header links must not carry page=3 — switching sort resets to page 1.
        # Find the author header link and assert there's no page param on it.
        author_link_idx = html.find("sort=author")
        assert author_link_idx != -1
        # Search the surrounding link tag — page=3 should be absent within
        # ~120 chars before/after the sort=author hit (within the href).
        window = html[max(0, author_link_idx - 200) : author_link_idx + 200]
        assert "page=3" not in window

    def test_pager_links_preserve_sort_and_dir(self, mock_catalog, client):
        books = [make_book(i) for i in range(1, 51)]
        _stub_browse(mock_catalog, books=books, total=120)

        response = client.get("/books?sort=author&dir=desc&page=2")
        html = response.data.decode()
        # Both prev and next should carry the active sort + dir.
        assert "sort=author" in html
        assert "dir=desc" in html
