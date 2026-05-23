# ABOUTME: Accessibility tests for the web UI per issue #112 acceptance criteria.
# ABOUTME: Validates skip-link, aria-live region, labels, and Back link semantics.

import re

from tests.web.conftest import make_book


class TestSkipLink:
    def test_skip_link_is_first_focusable(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)
        html = client.get("/books/1").data.decode()
        # Skip-link must appear before <main> in the document.
        assert "skip-link" in html
        body_idx = html.index("<body")
        skip_idx = html.index('href="#main"')
        main_idx = html.index("<main")
        assert body_idx < skip_idx < main_idx


class TestAriaLive:
    def test_book_content_has_aria_live(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)
        html = client.get("/books/1").data.decode()
        # The #book-content target announces htmx swaps politely.
        assert re.search(
            r'id="book-content"[^>]*aria-live="polite"|aria-live="polite"[^>]*id="book-content"',
            html,
        )


class TestEditFormLabels:
    def test_every_input_has_matching_label(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)
        html = client.get("/books/1/edit").data.decode()

        ids = set(re.findall(r'<(?:input|textarea)[^>]*id="([^"]+)"', html))
        label_fors = set(re.findall(r'<label[^>]*for="([^"]+)"', html))

        assert ids, "Edit form must have inputs with id attrs"
        assert ids <= label_fors, f"Inputs missing labels: {ids - label_fors}"


class TestBackLink:
    def test_back_link_present(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1)
        html = client.get("/books/1").data.decode()
        assert "Back to library" in html
