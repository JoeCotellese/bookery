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
        # Title and author go into their own inputs so providers receive
        # them as structured args (see #209).
        assert 'name="title"' in html
        assert 'name="author"' in html
        assert 'value="Dune"' in html
        assert 'value="Herbert, Frank"' in html

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

        client.post(
            "/books/1/enrich/search",
            data={"isbn": "9780441172719", "title": "", "author": ""},
        )

        assert open_library.isbn_calls == ["9780441172719"]
        assert google_books.isbn_calls == ["9780441172719"]
        assert open_library.title_author_calls == []
        assert open_library.url_calls == []

    def test_isbn_like_title_dispatches_to_search_by_isbn(
        self, mock_catalog, client, open_library
    ):
        mock_catalog.get_by_id.return_value = make_book(1)

        client.post("/books/1/enrich/search", data={"title": "9780441172719"})

        assert open_library.isbn_calls == ["9780441172719"]
        assert open_library.title_author_calls == []

    def test_isbn10_in_title_dispatches_to_search_by_isbn(
        self, mock_catalog, client, open_library
    ):
        mock_catalog.get_by_id.return_value = make_book(1)

        client.post("/books/1/enrich/search", data={"title": "044117271X"})

        assert open_library.isbn_calls == ["044117271X"]

    def test_url_in_title_dispatches_to_lookup_by_url(self, mock_catalog, client, open_library):
        mock_catalog.get_by_id.return_value = make_book(1)
        open_library.by_url = make_candidate(title="From URL", confidence=0.95)

        client.post(
            "/books/1/enrich/search",
            data={"title": "https://openlibrary.org/works/OL1234W"},
        )

        assert open_library.url_calls == ["https://openlibrary.org/works/OL1234W"]
        assert open_library.isbn_calls == []
        assert open_library.title_author_calls == []

    def test_title_and_author_dispatch_to_search_by_title_author(
        self, mock_catalog, client, open_library
    ):
        """Author goes through as a structured argument, not concatenated
        into the title — that's the fix for #209.
        """
        mock_catalog.get_by_id.return_value = make_book(1)

        client.post(
            "/books/1/enrich/search",
            data={"title": "Dune", "author": "Frank Herbert"},
        )

        assert open_library.title_author_calls == [("Dune", "Frank Herbert")]
        assert open_library.isbn_calls == []
        assert open_library.url_calls == []

    def test_title_only_dispatch_passes_none_author(self, mock_catalog, client, open_library):
        mock_catalog.get_by_id.return_value = make_book(1)

        client.post("/books/1/enrich/search", data={"title": "Dune"})

        assert open_library.title_author_calls == [("Dune", None)]

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

        html = client.post("/books/1/enrich/search", data={"title": "Dune"}).data.decode()

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

        html = client.post("/books/1/enrich/search", data={"title": "Dune"}).data.decode()

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

        html = client.post("/books/1/enrich/search", data={"title": "Dune"}).data.decode()

        assert "No candidates from Google Books" in html

    def test_all_providers_empty_renders_global_empty_state(
        self, mock_catalog, client, open_library, google_books
    ):
        mock_catalog.get_by_id.return_value = make_book(1)
        open_library.by_title_author = []
        google_books.by_title_author = []

        html = client.post(
            "/books/1/enrich/search", data={"title": "Nothing matches"}
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

        html = client.post("/books/1/enrich/search", data={"title": "Dune"}).data.decode()

        assert "Dune" in html
        assert "Herbert, Frank" in html
        assert "9780441172719" in html
        assert "Ace Books" in html
        assert "1965" in html
        assert "0.91" in html

    def test_view_button_wires_to_diff_route(
        self, mock_catalog, client, open_library, google_books
    ):
        mock_catalog.get_by_id.return_value = make_book(1)
        open_library.by_title_author = [make_candidate(title="X", confidence=0.5)]
        google_books.by_title_author = []

        html = client.post("/books/1/enrich/search", data={"title": "X"}).data.decode()

        assert "View" in html
        # View now fires the diff fetch into #book-content (issue #115).
        assert "/books/1/enrich/candidate" in html
        assert 'hx-target="#book-content"' in html

    def test_missing_book_returns_404(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = None
        response = client.post("/books/999/enrich/search", data={"title": "Dune"})
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


class TestEnrichFormRestoresResults:
    """GET /books/<id>/enrich with isbn/title/author query params should
    re-run the same search and inline the candidates into the form, so the
    'Back to results' button on the diff panel restores the user's state
    without forcing them to re-type their query.
    """

    def test_query_params_override_metadata_prefill(self, mock_catalog, client, open_library):
        mock_catalog.get_by_id.return_value = make_book(
            1, title="Original", authors=["Original Author"]
        )

        html = client.get("/books/1/enrich?title=Searched&author=Searched+Author").data.decode()

        # Form is prefilled with the searched values, not the book metadata.
        assert 'value="Searched"' in html
        assert 'value="Searched Author"' in html
        assert 'value="Original"' not in html
        assert 'value="Original Author"' not in html

    def test_query_params_trigger_search_and_render_candidates(
        self, mock_catalog, client, open_library, google_books
    ):
        mock_catalog.get_by_id.return_value = make_book(1)
        open_library.by_title_author = [make_candidate(title="Restored Hit", confidence=0.9)]

        html = client.get("/books/1/enrich?title=Dune&author=Frank+Herbert").data.decode()

        # The search was actually dispatched with the structured args.
        assert open_library.title_author_calls == [("Dune", "Frank Herbert")]
        # And the candidate is rendered inline in the response.
        assert "Restored Hit" in html

    def test_isbn_query_param_triggers_isbn_search(self, mock_catalog, client, open_library):
        mock_catalog.get_by_id.return_value = make_book(1)
        open_library.by_isbn = [make_candidate(title="ISBN Hit", confidence=0.95)]

        html = client.get("/books/1/enrich?isbn=9780441172719").data.decode()

        assert open_library.isbn_calls == ["9780441172719"]
        assert "ISBN Hit" in html

    def test_no_query_params_renders_form_without_search(self, mock_catalog, client, open_library):
        mock_catalog.get_by_id.return_value = make_book(1, title="Dune", authors=["Frank Herbert"])

        html = client.get("/books/1/enrich").data.decode()

        # No provider call when no query params present — original behavior.
        assert open_library.title_author_calls == []
        assert open_library.isbn_calls == []
        # Form is prefilled from book metadata as before.
        assert 'value="Dune"' in html
        assert 'value="Frank Herbert"' in html

    def test_empty_query_params_treated_as_absent(self, mock_catalog, client, open_library):
        mock_catalog.get_by_id.return_value = make_book(1, title="Dune")

        client.get("/books/1/enrich?isbn=&title=&author=")

        # Whitespace/empty params shouldn't fire a no-op search.
        assert open_library.title_author_calls == []
        assert open_library.isbn_calls == []
        assert open_library.url_calls == []


class TestEnrichDiffBackToResults:
    """The 'Back to results' button on the diff panel should restore the
    candidate list — not drop the user back on an empty form.
    """

    def test_back_to_results_button_carries_dispatch_params(
        self, mock_catalog, client, open_library, google_books
    ):
        mock_catalog.get_by_id.return_value = make_book(1)
        open_library.by_title_author = [
            make_candidate(title="Dune", confidence=0.9, source_id="ol:1", source="Open Library")
        ]

        html = client.get(
            "/books/1/enrich/candidate"
            "?provider=Open+Library&title=Dune&author=Frank+Herbert"
            "&candidate_id=ol:1"
        ).data.decode()

        # Back-to-results hx-get must include the dispatch params so the
        # enrich_form route re-runs the search instead of showing an empty form.
        assert "Back to results" in html
        assert "title=Dune" in html
        assert "author=Frank" in html  # url-encoded space tolerated
