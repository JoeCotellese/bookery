# ABOUTME: Tests for the apply-candidate enrichment flow — diff helper, GET, POST.
# ABOUTME: Covers metadata_diff unit tests, candidate re-fetch, apply write + catalog updates.

from unittest.mock import patch

import pytest

from bookery.core.pipeline import WriteResult
from bookery.metadata.candidate import MetadataCandidate
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

    def test_uses_library_copy_when_source_path_missing(
        self, mock_catalog, client, open_library, tmp_path
    ):
        """Imported books keep their original source_path even when the user
        deletes the original file (e.g. empties Calibre's trash). The library
        copy at output_path is the canonical file and must be used as the
        read source for enrichment in that case.
        """
        missing_source = tmp_path / "gone-from-calibre-trash.epub"  # never created
        library_copy = tmp_path / "library" / "Author - Title.epub"
        library_copy.parent.mkdir()
        library_copy.write_bytes(b"epub")

        mock_catalog.get_by_id.return_value = make_book(
            1, source_path=missing_source, output_path=library_copy
        )

        open_library.by_isbn = [
            make_candidate(source="Open Library", source_id="OL:1"),
        ]
        dest = tmp_path / "library" / "Author - Title (enriched).epub"

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

        # apply_metadata_safely must be called with the library copy as source,
        # writing into the library directory.
        mock_apply.assert_called_once()
        called_source, _called_metadata, called_output_dir = mock_apply.call_args.args
        assert called_source == library_copy
        assert called_output_dir == library_copy.parent

        # Catalog write proceeds normally.
        mock_catalog.update_book.assert_called_once()
        mock_catalog.set_output_path.assert_called_once_with(1, dest)
        assert response.headers.get("HX-Redirect") == "/books/1"

    def test_no_readable_file_flashes_error(
        self, mock_catalog, client, open_library, tmp_path
    ):
        """Both source_path and output_path missing → flash error, no writes."""
        missing_source = tmp_path / "missing-source.epub"
        missing_output = tmp_path / "missing-library.epub"
        mock_catalog.get_by_id.return_value = make_book(
            1, source_path=missing_source, output_path=missing_output
        )

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

        mock_apply.assert_not_called()
        mock_catalog.update_book.assert_not_called()
        mock_catalog.set_output_path.assert_not_called()
        assert response.headers.get("HX-Redirect") == "/books/1"

        with client.session_transaction() as session:
            flashes = session.get("_flashes", [])
        assert any(category == "error" for category, _ in flashes)

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


# --- description HTML stripping on apply (issue #123) -----------------------


class TestEnrichApplyStripsDescriptionHtml:
    """Apply-candidate path must strip HTML from provider descriptions."""

    def _apply_with_description(
        self,
        mock_catalog,
        client,
        open_library,
        tmp_path,
        proposed_description: str | None,
        *,
        current_description: str | None = None,
    ):
        source = tmp_path / "src.epub"
        source.write_bytes(b"epub")
        mock_catalog.get_by_id.return_value = make_book(
            1, source_path=source, description=current_description
        )
        candidate = MetadataCandidate(
            metadata=BookMetadata(
                title="T",
                authors=["A"],
                description=proposed_description,
            ),
            confidence=0.9,
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
        return mock_catalog.update_book.call_args

    def test_html_in_proposed_description_is_stripped(
        self, mock_catalog, client, open_library, tmp_path
    ):
        call = self._apply_with_description(
            mock_catalog,
            client,
            open_library,
            tmp_path,
            '<p class="description">A story.</p>',
        )
        assert call.kwargs["description"] == "A story."

    def test_entities_in_proposed_description_are_decoded(
        self, mock_catalog, client, open_library, tmp_path
    ):
        call = self._apply_with_description(
            mock_catalog, client, open_library, tmp_path, "foo &amp; bar"
        )
        assert call.kwargs["description"] == "foo & bar"

    def test_html_that_strips_to_same_as_current_does_not_write(
        self, mock_catalog, client, open_library, tmp_path
    ):
        # Current plain text matches what the HTML proposed value strips to.
        # The skip-clear / no-clobber guard from #125 also covers "no real
        # change" — make sure description isn't gratuitously re-written.
        call = self._apply_with_description(
            mock_catalog,
            client,
            open_library,
            tmp_path,
            "<p>Existing prose.</p>",
            current_description="Existing prose.",
        )
        assert "description" not in call.kwargs


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


# --- Skip-clear guard (issue #125) ------------------------------------------


class TestMetadataDiffSkipClear:
    """Diff helper flags rows where proposed is empty but current is set.

    These rows must surface as ``skip_clear`` so the apply handler can drop
    them and the diff UI can render the muted "current kept" treatment.
    """

    def test_empty_proposed_with_current_marked_skip_clear(self):
        current = BookMetadata(title="Dune", authors=["Stephen King"])
        proposed = BookMetadata(title="Dune", authors=[])

        diffs = metadata_diff(current, proposed)
        authors_diff = next(d for d in diffs if d.field == "authors")
        assert authors_diff.skip_clear is True
        assert authors_diff.changed is True

    def test_empty_scalar_proposed_with_current_marked_skip_clear(self):
        current = BookMetadata(title="Dune", publisher="Ace Books")
        proposed = BookMetadata(title="Dune", publisher="")

        diffs = metadata_diff(current, proposed)
        publisher_diff = next(d for d in diffs if d.field == "publisher")
        assert publisher_diff.skip_clear is True

    def test_none_scalar_proposed_with_current_marked_skip_clear(self):
        current = BookMetadata(title="Dune", isbn="9780441172719")
        proposed = BookMetadata(title="Dune", isbn=None)

        diffs = metadata_diff(current, proposed)
        isbn_diff = next(d for d in diffs if d.field == "isbn")
        assert isbn_diff.skip_clear is True

    def test_both_empty_not_skip_clear(self):
        current = BookMetadata(title="Dune", publisher=None)
        proposed = BookMetadata(title="Dune", publisher="")

        diffs = metadata_diff(current, proposed)
        publisher_diff = next(d for d in diffs if d.field == "publisher")
        # Both effectively empty → no change, not a skipped clear either.
        assert publisher_diff.skip_clear is False
        assert publisher_diff.changed is False

    def test_non_empty_proposed_not_skip_clear(self):
        current = BookMetadata(title="Dune", publisher="Ace Books")
        proposed = BookMetadata(title="Dune", publisher="Penguin")

        diffs = metadata_diff(current, proposed)
        publisher_diff = next(d for d in diffs if d.field == "publisher")
        assert publisher_diff.skip_clear is False
        assert publisher_diff.changed is True


class TestEnrichApplySkipClear:
    """Server-side guard: never overwrite a non-empty field with an empty one."""

    def test_empty_authors_does_not_overwrite_existing_authors(
        self, mock_catalog, client, open_library, tmp_path
    ):
        source = tmp_path / "src.epub"
        source.write_bytes(b"epub")
        mock_catalog.get_by_id.return_value = make_book(
            1, title="It", authors=["Stephen King"], source_path=source
        )

        # Candidate has empty authors — must NOT clobber existing "Stephen King".
        # Build the candidate directly so we can pin authors to an empty list
        # (make_candidate substitutes a default when given a falsy authors list).
        candidate = MetadataCandidate(
            metadata=BookMetadata(title="It", authors=[]),
            confidence=0.5,
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

        _, kwargs = mock_catalog.update_book.call_args
        # authors should NOT be passed (or, if passed, must equal current).
        assert "authors" not in kwargs or kwargs["authors"] == ["Stephen King"]

    def test_empty_scalar_does_not_overwrite_existing_scalar(
        self, mock_catalog, client, open_library, tmp_path
    ):
        source = tmp_path / "src.epub"
        source.write_bytes(b"epub")
        mock_catalog.get_by_id.return_value = make_book(
            1, title="Dune", publisher="Ace Books", source_path=source
        )

        candidate = make_candidate(
            title="Dune",
            authors=["Frank Herbert"],
            publisher="",
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

        _, kwargs = mock_catalog.update_book.call_args
        # publisher should not be sent through as an empty clearing value.
        assert "publisher" not in kwargs or kwargs["publisher"] == "Ace Books"

    def test_non_empty_proposed_still_overwrites(
        self, mock_catalog, client, open_library, tmp_path
    ):
        source = tmp_path / "src.epub"
        source.write_bytes(b"epub")
        mock_catalog.get_by_id.return_value = make_book(
            1, title="Old", authors=["Old Author"], source_path=source
        )

        candidate = make_candidate(
            title="New",
            authors=["New Author"],
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

        _, kwargs = mock_catalog.update_book.call_args
        assert kwargs["title"] == "New"
        assert kwargs["authors"] == ["New Author"]
        assert kwargs["publisher"] == "Acme"

    def test_empty_proposed_when_current_also_empty_is_noop(
        self, mock_catalog, client, open_library, tmp_path
    ):
        source = tmp_path / "src.epub"
        source.write_bytes(b"epub")
        # Current publisher is None; proposed publisher is "" — should be safe no-op.
        mock_catalog.get_by_id.return_value = make_book(
            1, title="Dune", publisher=None, source_path=source
        )

        candidate = make_candidate(
            title="Dune",
            authors=["Frank Herbert"],
            publisher="",
            source="Open Library",
            source_id="OL:1",
        )
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

        # Apply still succeeds; publisher simply not written.
        assert response.headers.get("HX-Redirect") == "/books/1"
        _, kwargs = mock_catalog.update_book.call_args
        assert "publisher" not in kwargs

    def test_empty_title_does_not_overwrite_existing_title(
        self, mock_catalog, client, open_library, tmp_path
    ):
        source = tmp_path / "src.epub"
        source.write_bytes(b"epub")
        mock_catalog.get_by_id.return_value = make_book(
            1, title="It", authors=["Stephen King"], source_path=source
        )

        # Even though title is "required" elsewhere, defend against a
        # candidate that somehow surfaces an empty title.
        candidate = make_candidate(
            title="",
            authors=["Stephen King"],
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

        _, kwargs = mock_catalog.update_book.call_args
        assert "title" not in kwargs or kwargs["title"] == "It"


class TestEnrichDiffSkipClearRendering:
    """The diff panel surfaces skip-clear rows with a muted indicator."""

    def test_skip_clear_row_has_diff_clear_class(self, mock_catalog, client, open_library):
        mock_catalog.get_by_id.return_value = make_book(1, title="It", authors=["Stephen King"])
        # Empty authors on the candidate → skip_clear row in the diff table.
        # Construct directly so the empty author list isn't replaced by a default.
        candidate = MetadataCandidate(
            metadata=BookMetadata(title="It", authors=[]),
            confidence=0.5,
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
        assert "diff-clear" in html
        # User-visible note explaining the skipped clear.
        assert "current kept" in html.lower()
