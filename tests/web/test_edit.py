# ABOUTME: Tests for the restructured edit form + provenance panel (issue #112).
# ABOUTME: Verifies provenance content, Esc keybind hook, and POST behavior preserved.

from pathlib import Path

from tests.web.conftest import make_book


class TestProvenancePanel:
    def test_provenance_panel_renders(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(
            1,
            source_path=Path("/books/test.epub"),
            output_path=Path("/library/test.epub"),
            file_hash="deadbeef",
            date_added="2026-01-01",
            date_modified="2026-01-02",
        )
        html = client.get("/books/1/edit").data.decode()
        assert "provenance" in html  # CSS class
        assert "/books/test.epub" in html
        assert "/library/test.epub" in html
        assert "deadbeef" in html
        assert "2026-01-01" in html
        assert "2026-01-02" in html

    def test_provenance_panel_dash_for_missing_output(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1, output_path=None)
        html = client.get("/books/1/edit").data.decode()
        # Provenance shows an em-dash for the missing output path.
        assert "—" in html


class TestEditFormKeybind:
    def test_edit_form_has_esc_keybind_handler(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)
        html = client.get("/books/1/edit").data.decode()
        # Inline JS that listens for Escape key to cancel the edit.
        assert "Escape" in html


class TestEditFormStructure:
    def test_required_marker_only_on_title(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)
        html = client.get("/books/1/edit").data.decode()
        assert html.count('class="required"') == 1


class TestUpdateStillRendersDetail:
    def test_post_returns_detail_partial_with_sections(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1, title="Updated")
        response = client.post(
            "/books/1/edit",
            data={
                "title": "Updated",
                "authors": "Author, Test",
                "isbn": "",
                "language": "",
                "publisher": "",
                "description": "",
                "series": "",
                "series_index": "",
            },
        )
        assert response.status_code == 200
        html = response.data.decode()
        assert "Updated" in html
        assert 'aria-labelledby="detail-header"' in html
