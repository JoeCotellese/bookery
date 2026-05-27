# ABOUTME: Tests for the restructured edit form + provenance panel (issue #112).
# ABOUTME: Verifies provenance content, Esc keybind hook, and POST behavior preserved.

import re
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


class TestProvenanceDisclosure:
    """Provenance is a collapsible disclosure below the form (issue #166)."""

    def _html(self, mock_catalog, client) -> str:
        mock_catalog.get_by_id.return_value = make_book(1)
        return client.get("/books/1/edit").data.decode()

    def test_provenance_is_a_details_element(self, mock_catalog, client):
        html = self._html(mock_catalog, client)
        # The panel must be wrapped in <details> so users can collapse it.
        assert "<details" in html and "</details>" in html

    def test_provenance_has_summary_label(self, mock_catalog, client):
        html = self._html(mock_catalog, client)
        assert re.search(r"<summary[^>]*>\s*Provenance\s*</summary>", html)

    def test_provenance_is_closed_by_default(self, mock_catalog, client):
        html = self._html(mock_catalog, client)
        # No `open` attribute — the disclosure is collapsed on first render.
        match = re.search(r"<details[^>]*>", html)
        assert match, "expected a <details> element"
        assert " open" not in match.group(0)

    def test_provenance_renders_below_the_form(self, mock_catalog, client):
        html = self._html(mock_catalog, client)
        form_end = html.rfind("</form>")
        provenance_start = html.find("<details")
        assert form_end != -1 and provenance_start != -1
        assert provenance_start > form_end


class TestProvenanceOverflowCss:
    """CSS rules that keep long provenance values inside the panel (issue #166)."""

    def _rule_block(self, client, selector: str) -> str:
        """Return the CSS declaration block for the given selector."""
        response = client.get("/static/style.css")
        assert response.status_code == 200
        css = response.data.decode()
        # Match `<selector> { ... }` (non-greedy, single block).
        match = re.search(
            rf"{re.escape(selector)}\s*\{{([^}}]*)\}}",
            css,
        )
        assert match, f"Selector {selector!r} not found in style.css"
        return match.group(1)

    def test_metadata_grid_value_track_can_shrink(self, client):
        # The value column must allow shrinking below content min-content so
        # long paths/hashes don't blow out the grid track.
        block = self._rule_block(client, ".metadata-grid")
        assert "minmax(0, 1fr)" in block

    def test_metadata_grid_dd_breaks_at_any_character(self, client):
        # dd values need overflow-wrap: anywhere so space-less strings
        # (hashes, deep paths) wrap inside the panel.
        block = self._rule_block(client, ".metadata-grid dd")
        assert "overflow-wrap: anywhere" in block
        assert "min-width: 0" in block

    def test_metadata_grid_code_breaks_at_any_character(self, client):
        # <code> inside the grid needs overflow-wrap so hash strings break.
        block = self._rule_block(client, ".metadata-grid code")
        assert "overflow-wrap: anywhere" in block


class TestDescriptionHtmlStripping:
    """Edit POSTs must store plain text — never HTML markup (issue #123)."""

    def _post_description(self, mock_catalog, client, description: str):
        mock_catalog.get_by_id.return_value = make_book(1, title="Book")
        client.post(
            "/books/1/edit",
            data={
                "title": "Book",
                "authors": "Author",
                "isbn": "",
                "language": "",
                "publisher": "",
                "description": description,
                "series": "",
                "series_index": "",
            },
        )
        return mock_catalog.update_book.call_args

    def test_html_tags_stripped_on_save(self, mock_catalog, client):
        call = self._post_description(mock_catalog, client, '<p class="description">A story.</p>')
        assert call.kwargs["description"] == "A story."

    def test_entities_decoded_on_save(self, mock_catalog, client):
        call = self._post_description(mock_catalog, client, "foo &amp; bar")
        assert call.kwargs["description"] == "foo & bar"

    def test_paragraphs_preserved_as_blank_lines(self, mock_catalog, client):
        call = self._post_description(mock_catalog, client, "<p>first</p><p>second</p>")
        assert call.kwargs["description"] == "first\n\nsecond"

    def test_empty_html_becomes_none(self, mock_catalog, client):
        call = self._post_description(mock_catalog, client, "<p></p>")
        assert call.kwargs["description"] is None

    def test_book_524_repro_case(self, mock_catalog, client):
        # The reported bug: stored values arrive with <p class="description">
        # wrappers that render as escaped text. After the fix the catalog
        # never sees that markup.
        call = self._post_description(
            mock_catalog,
            client,
            '<p class="description">A great story about &amp;c.</p>',
        )
        assert call.kwargs["description"] == "A great story about &c."
        assert "<p" not in call.kwargs["description"]
