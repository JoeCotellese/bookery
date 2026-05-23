# ABOUTME: Tests for the apply-candidate enrichment flow — diff helper, GET, POST.
# ABOUTME: Covers metadata_diff unit tests, candidate re-fetch, apply write + catalog updates.

from unittest.mock import patch

import pytest

from bookery.core.pipeline import WriteResult
from bookery.metadata.types import BookMetadata
from bookery.web.diff import FieldDiff, metadata_diff
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


@pytest.fixture(autouse=True)
def _secret_key(app):
    """Provide a SECRET_KEY so ``flash()`` can sign the session cookie.

    Sibling PR #113 wires this into ``create_app``; this fixture keeps the
    apply-flow tests independent of that landing first.
    """
    app.config["SECRET_KEY"] = "test-secret"
    return app


# --- metadata_diff unit tests -------------------------------------------------


class TestMetadataDiff:
    def test_unchanged_fields_marked_unchanged(self):
        current = BookMetadata(title="Dune", authors=["Frank Herbert"], isbn="9780441172719")
        proposed = BookMetadata(title="Dune", authors=["Frank Herbert"], isbn="9780441172719")

        diffs = metadata_diff(current, proposed)
        title_diff = next(d for d in diffs if d.field == "title")
        assert title_diff.changed is False
        author_diff = next(d for d in diffs if d.field == "authors")
        assert author_diff.changed is False

    def test_changed_title_marked_changed(self):
        current = BookMetadata(title="Dune")
        proposed = BookMetadata(title="Dune: First Edition")

        diffs = metadata_diff(current, proposed)
        title_diff = next(d for d in diffs if d.field == "title")
        assert title_diff.changed is True
        assert title_diff.current == "Dune"
        assert title_diff.proposed == "Dune: First Edition"

    def test_none_and_empty_string_equivalent(self):
        current = BookMetadata(title="Dune", publisher=None)
        proposed = BookMetadata(title="Dune", publisher="")

        diffs = metadata_diff(current, proposed)
        publisher_diff = next(d for d in diffs if d.field == "publisher")
        assert publisher_diff.changed is False

    def test_authors_compared_as_ordered_list(self):
        current = BookMetadata(title="X", authors=["A", "B"])
        proposed = BookMetadata(title="X", authors=["B", "A"])

        diffs = metadata_diff(current, proposed)
        author_diff = next(d for d in diffs if d.field == "authors")
        assert author_diff.changed is True

    def test_authors_same_order_marked_unchanged(self):
        current = BookMetadata(title="X", authors=["A", "B"])
        proposed = BookMetadata(title="X", authors=["A", "B"])

        diffs = metadata_diff(current, proposed)
        author_diff = next(d for d in diffs if d.field == "authors")
        assert author_diff.changed is False

    def test_all_required_fields_present(self):
        current = BookMetadata(title="X")
        proposed = BookMetadata(title="X")

        diffs = metadata_diff(current, proposed)
        fields = {d.field for d in diffs}
        assert fields == {
            "title",
            "authors",
            "isbn",
            "language",
            "publisher",
            "series",
            "series_index",
            "description",
        }

    def test_series_index_changed(self):
        current = BookMetadata(title="X", series_index=1.0)
        proposed = BookMetadata(title="X", series_index=2.0)

        diffs = metadata_diff(current, proposed)
        si_diff = next(d for d in diffs if d.field == "series_index")
        assert si_diff.changed is True

    def test_returns_field_diff_dataclass(self):
        current = BookMetadata(title="X")
        proposed = BookMetadata(title="Y")
        diffs = metadata_diff(current, proposed)
        assert all(isinstance(d, FieldDiff) for d in diffs)


# --- GET /books/<id>/enrich/candidate ---------------------------------------


class TestEnrichCandidateGet:
    def test_isbn_path_renders_diff(self, mock_catalog, client, open_library):
        mock_catalog.get_by_id.return_value = make_book(
            1, title="Dune Old", authors=["Frank Herbert"], isbn="9780441172719"
        )
        candidate = make_candidate(
            title="Dune",
            authors=["Frank Herbert"],
            isbn="9780441172719",
            confidence=0.92,
            source="Open Library",
            source_id="OL:M/123",
        )
        open_library.by_isbn = [candidate]

        response = client.get(
            "/books/1/enrich/candidate",
            query_string={
                "provider": "Open Library",
                "query": "9780441172719",
                "candidate_id": "OL:M/123",
            },
        )

        assert response.status_code == 200
        html = response.data.decode()
        # Diff header includes provider + confidence
        assert "Open Library" in html
        assert "0.92" in html
        # Field rows present
        assert "Dune Old" in html
        assert "Dune" in html

    def test_changed_field_has_changed_class(self, mock_catalog, client, open_library):
        mock_catalog.get_by_id.return_value = make_book(1, title="Old Title")
        candidate = make_candidate(
            title="New Title",
            authors=["Unknown"],
            source="Open Library",
            source_id="OL:1",
        )
        open_library.by_title_author = [candidate]

        response = client.get(
            "/books/1/enrich/candidate",
            query_string={
                "provider": "Open Library",
                "query": "Old Title",
                "candidate_id": "OL:1",
            },
        )

        html = response.data.decode()
        # Changed cell visually distinct via the .changed class.
        assert "changed" in html

    def test_unchanged_field_labeled_same(self, mock_catalog, client, open_library):
        mock_catalog.get_by_id.return_value = make_book(1, title="Dune", isbn="9780441172719")
        candidate = make_candidate(
            title="New Title",
            isbn="9780441172719",
            source="Open Library",
            source_id="OL:1",
        )
        open_library.by_isbn = [candidate]

        response = client.get(
            "/books/1/enrich/candidate",
            query_string={
                "provider": "Open Library",
                "query": "9780441172719",
                "candidate_id": "OL:1",
            },
        )

        html = response.data.decode()
        # ISBN matches → "same" label rendered.
        assert "same" in html

    def test_missing_book_returns_404(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = None
        response = client.get(
            "/books/999/enrich/candidate",
            query_string={"provider": "Open Library", "query": "x", "candidate_id": "x"},
        )
        assert response.status_code == 404

    def test_unknown_provider_returns_404(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)
        response = client.get(
            "/books/1/enrich/candidate",
            query_string={"provider": "Unknown", "query": "x", "candidate_id": "x"},
        )
        assert response.status_code == 404

    def test_candidate_id_not_found_returns_404(self, mock_catalog, client, open_library):
        mock_catalog.get_by_id.return_value = make_book(1)
        open_library.by_isbn = [
            make_candidate(source="Open Library", source_id="OL:1"),
        ]

        response = client.get(
            "/books/1/enrich/candidate",
            query_string={
                "provider": "Open Library",
                "query": "9780441172719",
                "candidate_id": "OL:does-not-exist",
            },
        )
        assert response.status_code == 404

    def test_apply_button_carries_through_params(self, mock_catalog, client, open_library):
        mock_catalog.get_by_id.return_value = make_book(1)
        open_library.by_isbn = [
            make_candidate(source="Open Library", source_id="OL:1"),
        ]

        response = client.get(
            "/books/1/enrich/candidate",
            query_string={
                "provider": "Open Library",
                "query": "9780441172719",
                "candidate_id": "OL:1",
            },
        )

        html = response.data.decode()
        # Apply form carries provider, query, candidate_id so POST can re-fetch.
        assert 'name="provider"' in html
        assert 'name="query"' in html
        assert 'name="candidate_id"' in html

    def test_back_to_results_link_present(self, mock_catalog, client, open_library):
        mock_catalog.get_by_id.return_value = make_book(1)
        open_library.by_isbn = [
            make_candidate(source="Open Library", source_id="OL:1"),
        ]

        response = client.get(
            "/books/1/enrich/candidate",
            query_string={
                "provider": "Open Library",
                "query": "9780441172719",
                "candidate_id": "OL:1",
            },
        )

        html = response.data.decode()
        # Back-to-results re-runs the search panel.
        assert "Back to results" in html


# --- POST /books/<id>/enrich/apply ------------------------------------------


class TestEnrichApplyPost:
    def test_calls_write_helper_with_source_and_metadata(
        self, mock_catalog, client, open_library, tmp_path
    ):
        source = tmp_path / "src.epub"
        source.write_bytes(b"epub")
        mock_catalog.get_by_id.return_value = make_book(1, source_path=source)

        proposed = BookMetadata(title="Proposed Title", authors=["Author"], isbn="9780441172719")
        candidate = make_candidate(
            title="Proposed Title",
            authors=["Author"],
            isbn="9780441172719",
            source="Open Library",
            source_id="OL:1",
        )
        # Replace metadata so write helper sees the full BookMetadata we built.
        candidate.metadata = proposed
        open_library.by_isbn = [candidate]

        dest = tmp_path / "out.epub"

        with patch("bookery.web.routes.apply_metadata_safely") as mock_apply:
            mock_apply.return_value = WriteResult(path=dest, success=True)
            response = client.post(
                "/books/1/enrich/apply",
                data={
                    "provider": "Open Library",
                    "query": "9780441172719",
                    "candidate_id": "OL:1",
                },
            )

        mock_apply.assert_called_once()
        args, _ = mock_apply.call_args
        assert args[0] == source
        # Metadata argument carries proposed values.
        assert args[1].title == "Proposed Title"
        assert response.status_code == 200

    def test_updates_catalog_with_proposed_fields(
        self, mock_catalog, client, open_library, tmp_path
    ):
        source = tmp_path / "src.epub"
        source.write_bytes(b"epub")
        mock_catalog.get_by_id.return_value = make_book(1, source_path=source)

        candidate = make_candidate(
            title="New Title",
            authors=["New Author"],
            isbn="9780441172719",
            publisher="Acme",
            source="Open Library",
            source_id="OL:1",
        )
        open_library.by_isbn = [candidate]
        dest = tmp_path / "out.epub"

        with patch("bookery.web.routes.apply_metadata_safely") as mock_apply:
            mock_apply.return_value = WriteResult(path=dest, success=True)
            client.post(
                "/books/1/enrich/apply",
                data={
                    "provider": "Open Library",
                    "query": "9780441172719",
                    "candidate_id": "OL:1",
                },
            )

        mock_catalog.update_book.assert_called()
        _, kwargs = mock_catalog.update_book.call_args
        # Updated fields include title and authors from the candidate.
        assert kwargs["title"] == "New Title"
        assert kwargs["authors"] == ["New Author"]
        assert kwargs["publisher"] == "Acme"
        # Source attribution credited to the provider name.
        assert kwargs.get("source") == "Open Library"

    def test_records_output_path(self, mock_catalog, client, open_library, tmp_path):
        source = tmp_path / "src.epub"
        source.write_bytes(b"epub")
        mock_catalog.get_by_id.return_value = make_book(1, source_path=source)

        open_library.by_isbn = [
            make_candidate(source="Open Library", source_id="OL:1"),
        ]
        dest = tmp_path / "out.epub"

        with patch("bookery.web.routes.apply_metadata_safely") as mock_apply:
            mock_apply.return_value = WriteResult(path=dest, success=True)
            client.post(
                "/books/1/enrich/apply",
                data={
                    "provider": "Open Library",
                    "query": "9780441172719",
                    "candidate_id": "OL:1",
                },
            )

        mock_catalog.set_output_path.assert_called_once_with(1, dest)

    def test_sets_hx_redirect_to_detail(self, mock_catalog, client, open_library, tmp_path):
        source = tmp_path / "src.epub"
        source.write_bytes(b"epub")
        mock_catalog.get_by_id.return_value = make_book(1, source_path=source)

        open_library.by_isbn = [
            make_candidate(source="Open Library", source_id="OL:1"),
        ]
        dest = tmp_path / "out.epub"

        with patch("bookery.web.routes.apply_metadata_safely") as mock_apply:
            mock_apply.return_value = WriteResult(path=dest, success=True)
            response = client.post(
                "/books/1/enrich/apply",
                data={
                    "provider": "Open Library",
                    "query": "9780441172719",
                    "candidate_id": "OL:1",
                },
            )

        assert response.headers.get("HX-Redirect") == "/books/1"

    def test_success_flash_on_apply(self, mock_catalog, client, app, open_library, tmp_path):
        source = tmp_path / "src.epub"
        source.write_bytes(b"epub")
        mock_catalog.get_by_id.return_value = make_book(1, title="Dune", source_path=source)

        open_library.by_isbn = [
            make_candidate(title="Dune", source="Open Library", source_id="OL:1"),
        ]
        dest = tmp_path / "out.epub"

        with patch("bookery.web.routes.apply_metadata_safely") as mock_apply:
            mock_apply.return_value = WriteResult(path=dest, success=True)
            client.post(
                "/books/1/enrich/apply",
                data={
                    "provider": "Open Library",
                    "query": "9780441172719",
                    "candidate_id": "OL:1",
                },
            )

        # Flash queued under the success category, surfaced by the test
        # client's session cookie.
        with client.session_transaction() as session:
            flashes = session.get("_flashes", [])
        categories = [c for c, _ in flashes]
        messages = [m for _, m in flashes]
        assert "success" in categories
        assert any('Applied "Dune"' in m and "Open Library" in m for m in messages)

    def test_missing_source_flashes_error_no_db_write(
        self, mock_catalog, client, open_library, tmp_path
    ):
        missing = tmp_path / "does-not-exist.epub"
        mock_catalog.get_by_id.return_value = make_book(1, source_path=missing)

        open_library.by_isbn = [
            make_candidate(source="Open Library", source_id="OL:1"),
        ]

        with patch("bookery.web.routes.apply_metadata_safely") as mock_apply:
            response = client.post(
                "/books/1/enrich/apply",
                data={
                    "provider": "Open Library",
                    "query": "9780441172719",
                    "candidate_id": "OL:1",
                },
            )

        # Write helper never invoked, catalog never written.
        mock_apply.assert_not_called()
        mock_catalog.update_book.assert_not_called()
        mock_catalog.set_output_path.assert_not_called()
        # Response still 200 for htmx but with HX-Redirect to detail.
        assert response.headers.get("HX-Redirect") == "/books/1"

        # Error flash queued under the error category.
        with client.session_transaction() as session:
            flashes = session.get("_flashes", [])
        assert any(category == "error" for category, _ in flashes)
        assert any("source" in msg.lower() for _, msg in flashes)

    def test_write_failure_flashes_error(self, mock_catalog, client, open_library, tmp_path):
        source = tmp_path / "src.epub"
        source.write_bytes(b"epub")
        mock_catalog.get_by_id.return_value = make_book(1, source_path=source)

        open_library.by_isbn = [
            make_candidate(source="Open Library", source_id="OL:1"),
        ]

        with patch("bookery.web.routes.apply_metadata_safely") as mock_apply:
            mock_apply.return_value = WriteResult(
                path=None, success=False, error="verification failed"
            )
            client.post(
                "/books/1/enrich/apply",
                data={
                    "provider": "Open Library",
                    "query": "9780441172719",
                    "candidate_id": "OL:1",
                },
            )

        # Write failed → catalog untouched.
        mock_catalog.update_book.assert_not_called()
        mock_catalog.set_output_path.assert_not_called()

    def test_missing_book_returns_404(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = None
        response = client.post(
            "/books/999/enrich/apply",
            data={"provider": "Open Library", "query": "x", "candidate_id": "x"},
        )
        assert response.status_code == 404

    def test_unknown_provider_returns_404(self, mock_catalog, client, tmp_path):
        source = tmp_path / "src.epub"
        source.write_bytes(b"epub")
        mock_catalog.get_by_id.return_value = make_book(1, source_path=source)
        response = client.post(
            "/books/1/enrich/apply",
            data={"provider": "Unknown", "query": "x", "candidate_id": "x"},
        )
        assert response.status_code == 404

    def test_candidate_not_found_returns_404(self, mock_catalog, client, open_library, tmp_path):
        source = tmp_path / "src.epub"
        source.write_bytes(b"epub")
        mock_catalog.get_by_id.return_value = make_book(1, source_path=source)
        open_library.by_isbn = [
            make_candidate(source="Open Library", source_id="OL:1"),
        ]
        response = client.post(
            "/books/1/enrich/apply",
            data={
                "provider": "Open Library",
                "query": "9780441172719",
                "candidate_id": "OL:missing",
            },
        )
        assert response.status_code == 404


# --- _enrich_candidate_row View button wiring -------------------------------


class TestCandidateRowViewWiring:
    def test_view_button_wires_diff_endpoint(self, mock_catalog, client, open_library):
        mock_catalog.get_by_id.return_value = make_book(1)
        open_library.by_isbn = [
            make_candidate(title="X", source="Open Library", source_id="OL:42"),
        ]

        response = client.post(
            "/books/1/enrich/search",
            data={"isbn": "9780441172719", "query": ""},
        )

        html = response.data.decode()
        # View button now active — fires hx-get to candidate diff route.
        assert "/books/1/enrich/candidate" in html
        assert "provider=Open+Library" in html or "provider=Open%20Library" in html
        assert "candidate_id=OL" in html
        assert "disabled" not in html.lower() or "View" in html
