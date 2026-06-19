# ABOUTME: Tests for the restructured book detail page (issue #112).
# ABOUTME: Verifies section partials, file context, toolbar placeholders, and enriched badge.

from pathlib import Path

from tests.web.conftest import make_book


class TestDetailSections:
    def test_header_section_present(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(
            1, title="Dune", authors=["Herbert, Frank"]
        )

        html = client.get("/books/1").data.decode()
        assert 'aria-labelledby="detail-header"' in html
        assert "Dune" in html
        assert "Herbert, Frank" in html

    def test_identity_section_present(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(
            1, isbn="9780441172719", language="en", series="Dune Chronicles", series_index=1.0
        )

        html = client.get("/books/1").data.decode()
        assert 'aria-labelledby="detail-identity"' in html
        assert "<h2" in html and "Identity" in html
        assert "9780441172719" in html
        assert "en" in html
        assert "Dune Chronicles" in html

    def test_publication_section_present(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1, publisher="Ace Books")

        html = client.get("/books/1").data.decode()
        assert 'aria-labelledby="detail-publication"' in html
        assert "Publication" in html
        assert "Ace Books" in html

    def test_classification_section_present(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)
        mock_catalog.get_tags_for_book.return_value = ["sci-fi"]
        mock_catalog.get_genres_for_book.return_value = [("Science Fiction", True)]

        html = client.get("/books/1").data.decode()
        assert 'aria-labelledby="detail-classification"' in html
        assert "Classification" in html
        assert "sci-fi" in html
        assert "Science Fiction" in html

    def test_file_section_present(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(
            1,
            source_path=Path("/books/test.epub"),
            file_hash="deadbeef",
            date_added="2026-01-01",
            date_modified="2026-01-02",
        )

        html = client.get("/books/1").data.decode()
        assert 'aria-labelledby="detail-file"' in html
        assert "File" in html
        assert "deadbeef" in html
        assert "2026-01-01" in html
        assert "2026-01-02" in html

    def test_file_section_renders_dash_when_stat_fails(self, mock_catalog, client):
        # /nonexistent path → stat() raises, size renders as em-dash.
        mock_catalog.get_by_id.return_value = make_book(
            1, source_path=Path("/nonexistent/missing.epub")
        )

        html = client.get("/books/1").data.decode()
        assert "—" in html  # em-dash fallback for size
        # Format from extension still works
        assert "EPUB" in html

    def test_file_section_shows_format_from_extension(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1, source_path=Path("/books/foo.epub"))

        html = client.get("/books/1").data.decode()
        assert "EPUB" in html

    def test_description_section_only_when_present(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1, description="A great story.")
        html = client.get("/books/1").data.decode()
        assert 'aria-labelledby="detail-description"' in html
        assert "A great story." in html

    def test_description_section_omitted_when_empty(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1, description=None)
        html = client.get("/books/1").data.decode()
        assert 'aria-labelledby="detail-description"' not in html

    def test_description_wraps_blank_line_paragraphs_in_p_tags(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(
            1, description="first paragraph\n\nsecond paragraph"
        )
        html = client.get("/books/1").data.decode()
        assert "<p>first paragraph</p>" in html
        assert "<p>second paragraph</p>" in html

    def test_description_does_not_render_literal_html_class_attr(self, mock_catalog, client):
        # If the catalog still held HTML (legacy data before migration), the
        # render layer would escape it. After issue #123 the catalog stores
        # plain text, so the literal '<p class="description">' string the
        # bug report flagged never appears on the detail page.
        mock_catalog.get_by_id.return_value = make_book(1, description="Plain prose, no markup.")
        html = client.get("/books/1").data.decode()
        assert "&lt;p class=&#34;description&#34;&gt;" not in html
        assert '<p class="description">' not in html
        assert "<p>Plain prose, no markup.</p>" in html

    def test_description_escapes_special_chars(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1, description="A & B")
        html = client.get("/books/1").data.decode()
        assert "<p>A &amp; B</p>" in html


class TestEnrichedBadge:
    def test_badge_shown_when_metadata_matched(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(
            1,
            output_path=Path("/library/test.epub"),
            metadata_matched_at="2026-05-01T00:00:00",
        )

        html = client.get("/books/1").data.decode()
        assert "Enriched" in html

    def test_badge_absent_when_not_matched_even_if_in_library(self, mock_catalog, client):
        # output_path alone (library-canonical) must NOT trigger the badge —
        # only an explicit metadata_matched_at counts.
        mock_catalog.get_by_id.return_value = make_book(
            1,
            output_path=Path("/library/test.epub"),
            metadata_matched_at=None,
        )
        html = client.get("/books/1").data.decode()
        assert "Enriched" not in html

    def test_badge_absent_when_output_path_missing(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(
            1,
            output_path=None,
            metadata_matched_at=None,
        )
        html = client.get("/books/1").data.decode()
        assert "Enriched" not in html


class TestToolbar:
    def test_toolbar_has_role(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)
        html = client.get("/books/1").data.decode()
        assert 'role="toolbar"' in html

    def test_toolbar_has_edit_active(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)
        html = client.get("/books/1").data.decode()
        # Edit button must include hx-get to edit endpoint
        assert "/books/1/edit" in html
        assert "Edit" in html

    def test_toolbar_has_enrich_and_delete_active(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)
        html = client.get("/books/1").data.decode()
        assert "Enrich" in html
        assert "Delete" in html
        # Enrich is wired to the search route (#114).
        assert "/books/1/enrich" in html
        # Delete is wired to the confirm route (#113).
        assert "/books/1/delete" in html
        assert 'title="Coming soon"' not in html
        # Delete uses destructive styling.
        assert "btn-destructive" in html


class TestEnrichPanelSlot:
    def test_enrich_panel_div_present(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)
        html = client.get("/books/1").data.decode()
        assert 'id="enrich-panel"' in html
