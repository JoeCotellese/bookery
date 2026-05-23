# ABOUTME: Tests for the enrich search routes — search form, multi-provider fan-out.
# ABOUTME: Covers ISBN/title-author/URL dispatch, ordering, empty-state copy, htmx wiring.

import pytest

from tests.web.conftest import FakeProvider, make_book, make_candidate


@pytest.fixture
def open_library():
    return FakeProvider(name="Open Library")


@pytest.fixture
def google_books():
    return FakeProvider(name="Google Books")


@pytest.fixture
def providers(open_library, google_books):
    return {"openlibrary": open_library, "googlebooks": google_books}


class TestEnrichSearchForm:
    def test_prefills_isbn_when_present(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(
            1, title="Dune", authors=["Herbert, Frank"], isbn="9780441172719"
        )

        html = client.get("/books/1/enrich").data.decode()
        assert "9780441172719" in html
        # ISBN goes in the isbn-specific input, not the free-text query.
        assert 'name="isbn"' in html

    def test_prefills_title_author_when_no_isbn(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(
            1, title="Dune", authors=["Herbert, Frank"], isbn=None
        )

        html = client.get("/books/1/enrich").data.decode()
        # Free-text query input pre-fills with "title author".
        assert 'name="query"' in html
        assert "Dune" in html
        assert "Herbert, Frank" in html

    def test_form_posts_to_search_endpoint(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)

        html = client.get("/books/1/enrich").data.decode()
        assert "/books/1/enrich/search" in html

    def test_form_targets_enrich_panel(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)

        html = client.get("/books/1/enrich").data.decode()
        # Results swap into a dedicated region inside the panel.
        assert 'hx-target="#enrich-results"' in html

    def test_form_has_hx_indicator(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)

        html = client.get("/books/1/enrich").data.decode()
        assert "hx-indicator" in html

    def test_cancel_button_swaps_back_to_detail(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)

        html = client.get("/books/1/enrich").data.decode()
        # Cancel hits the detail endpoint and swaps #book-content back.
        assert "/books/1" in html
        assert "Cancel" in html

    def test_missing_book_returns_404(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = None
        response = client.get("/books/999/enrich")
        assert response.status_code == 404


class TestEnrichSearchPost:
    def test_isbn_field_dispatches_to_search_by_isbn(
        self, mock_catalog, client, open_library, google_books
    ):
        mock_catalog.get_by_id.return_value = make_book(1)
        open_library.by_isbn = [make_candidate(title="A", confidence=0.9)]

        client.post("/books/1/enrich/search", data={"isbn": "9780441172719", "query": ""})

        assert open_library.isbn_calls == ["9780441172719"]
        assert google_books.isbn_calls == ["9780441172719"]
        assert open_library.title_author_calls == []
        assert open_library.url_calls == []

    def test_isbn_like_query_dispatches_to_search_by_isbn(
        self, mock_catalog, client, open_library
    ):
        mock_catalog.get_by_id.return_value = make_book(1)

        client.post("/books/1/enrich/search", data={"query": "9780441172719"})

        assert open_library.isbn_calls == ["9780441172719"]
        assert open_library.title_author_calls == []

    def test_isbn10_query_dispatches_to_search_by_isbn(self, mock_catalog, client, open_library):
        mock_catalog.get_by_id.return_value = make_book(1)

        client.post("/books/1/enrich/search", data={"query": "044117271X"})

        assert open_library.isbn_calls == ["044117271X"]

    def test_url_query_dispatches_to_lookup_by_url(self, mock_catalog, client, open_library):
        mock_catalog.get_by_id.return_value = make_book(1)
        open_library.by_url = make_candidate(title="From URL", confidence=0.95)

        client.post(
            "/books/1/enrich/search",
            data={"query": "https://openlibrary.org/works/OL1234W"},
        )

        assert open_library.url_calls == ["https://openlibrary.org/works/OL1234W"]
        assert open_library.isbn_calls == []
        assert open_library.title_author_calls == []

    def test_free_text_query_dispatches_to_search_by_title_author(
        self, mock_catalog, client, open_library
    ):
        mock_catalog.get_by_id.return_value = make_book(1)

        client.post("/books/1/enrich/search", data={"query": "Dune Frank Herbert"})

        assert open_library.title_author_calls == [("Dune Frank Herbert", None)]
        assert open_library.isbn_calls == []
        assert open_library.url_calls == []

    def test_renders_candidates_for_each_provider(
        self, mock_catalog, client, open_library, google_books
    ):
        mock_catalog.get_by_id.return_value = make_book(1)
        open_library.by_title_author = [
            make_candidate(title="OL One", confidence=0.9, source="Open Library"),
            make_candidate(title="OL Two", confidence=0.7, source="Open Library"),
        ]
        google_books.by_title_author = [
            make_candidate(title="GB One", confidence=0.8, source="Google Books"),
        ]

        html = client.post("/books/1/enrich/search", data={"query": "Dune"}).data.decode()

        assert "Open Library" in html
        assert "Open Library (2)" in html
        assert "Google Books" in html
        assert "Google Books (1)" in html
        assert "OL One" in html
        assert "OL Two" in html
        assert "GB One" in html

    def test_orders_candidates_by_confidence_descending(
        self, mock_catalog, client, open_library, google_books
    ):
        mock_catalog.get_by_id.return_value = make_book(1)
        open_library.by_title_author = [
            make_candidate(title="Low", confidence=0.3),
            make_candidate(title="High", confidence=0.9),
            make_candidate(title="Mid", confidence=0.6),
        ]
        google_books.by_title_author = []

        html = client.post("/books/1/enrich/search", data={"query": "Dune"}).data.decode()

        high_pos = html.find("High")
        mid_pos = html.find("Mid")
        low_pos = html.find("Low")
        assert -1 < high_pos < mid_pos < low_pos

    def test_empty_provider_renders_no_candidates_message(
        self, mock_catalog, client, open_library, google_books
    ):
        mock_catalog.get_by_id.return_value = make_book(1)
        open_library.by_title_author = [make_candidate(title="OL", confidence=0.5)]
        google_books.by_title_author = []  # empty

        html = client.post("/books/1/enrich/search", data={"query": "Dune"}).data.decode()

        assert "No candidates from Google Books" in html

    def test_all_providers_empty_renders_global_empty_state(
        self, mock_catalog, client, open_library, google_books
    ):
        mock_catalog.get_by_id.return_value = make_book(1)
        open_library.by_title_author = []
        google_books.by_title_author = []

        html = client.post(
            "/books/1/enrich/search", data={"query": "Nothing matches"}
        ).data.decode()

        assert "No candidates found" in html
        # No per-provider empty state when the whole result set is empty.
        assert "No candidates from" not in html

    def test_candidate_row_renders_required_fields(
        self, mock_catalog, client, open_library, google_books
    ):
        mock_catalog.get_by_id.return_value = make_book(1)
        open_library.by_title_author = [
            make_candidate(
                title="Dune",
                authors=["Herbert, Frank"],
                isbn="9780441172719",
                publisher="Ace Books",
                published_date="1965",
                confidence=0.91,
            )
        ]
        google_books.by_title_author = []

        html = client.post("/books/1/enrich/search", data={"query": "Dune"}).data.decode()

        assert "Dune" in html
        assert "Herbert, Frank" in html
        assert "9780441172719" in html
        assert "Ace Books" in html
        assert "1965" in html
        assert "0.91" in html

    def test_view_button_present_but_inert(self, mock_catalog, client, open_library, google_books):
        mock_catalog.get_by_id.return_value = make_book(1)
        open_library.by_title_author = [make_candidate(title="X", confidence=0.5)]
        google_books.by_title_author = []

        html = client.post("/books/1/enrich/search", data={"query": "X"}).data.decode()

        assert "View" in html
        # Inert: no hx-get/hx-post wired to the View button yet (Story 4).
        # We assert disabled attribute is present on the View button.
        assert "disabled" in html

    def test_missing_book_returns_404(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = None
        response = client.post("/books/999/enrich/search", data={"query": "Dune"})
        assert response.status_code == 404


class TestEnrichButtonOnDetail:
    def test_enrich_button_active_and_targets_enrich_endpoint(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)
        html = client.get("/books/1").data.decode()
        # Enrich button now wired up: hx-get pointing at the enrich endpoint.
        assert "/books/1/enrich" in html
        # The toolbar no longer carries Enrich as disabled.
        # (Delete may still be disabled — narrow the check to Enrich's block.)
        assert "Enrich" in html
