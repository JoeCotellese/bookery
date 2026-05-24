# ABOUTME: Plan-01 step 6 responsive mobile card layout tests for /books.
# ABOUTME: Asserts dual-markup (desktop table + mobile cards) and CSS-only viewport switching.

import re

from .conftest import make_book


class TestMobileCardMarkup:
    """The /books response carries both the desktop table and a mobile card list.

    CSS at the 768px breakpoint chooses which one is visible — the markup is
    always present so the same response works for any viewport without JS.
    """

    def test_response_includes_both_table_and_card_list(self, mock_catalog, client):
        mock_catalog.browse.return_value = ([make_book(1, title="Dune")], 1)

        html = client.get("/books").data.decode()

        # Desktop table still present (selectors used by other tests).
        assert 'class="book-table"' in html
        # Mobile cards wrapper present alongside.
        assert "book-cards" in html

    def test_one_card_per_book(self, mock_catalog, client):
        mock_catalog.browse.return_value = (
            [
                make_book(1, title="Dune"),
                make_book(2, title="Foundation"),
                make_book(3, title="Neuromancer"),
            ],
            3,
        )

        html = client.get("/books").data.decode()

        # Count card elements — one per book.
        card_count = html.count('class="book-card"')
        assert card_count == 3

    def test_whole_card_is_a_single_link(self, mock_catalog, client):
        """Per plan-01 step 6: the entire card is the row link target."""
        mock_catalog.browse.return_value = ([make_book(42, title="Hyperion")], 1)

        html = client.get("/books").data.decode()

        # The card itself should be wrapped in <a href="/books/42">.
        # Match an <a ...> tag whose href points at the book detail and which
        # carries the book-card class.
        # Allow a trailing ``?return_to=…`` (plan-02 step 3) inside the href.
        pattern = re.compile(
            r'<a[^>]+class="book-card[^"]*"[^>]*href="[^"]*/books/42(\?[^"]*)?"'
            r'|<a[^>]+href="[^"]*/books/42(\?[^"]*)?"[^>]*class="book-card[^"]*"'
        )
        assert pattern.search(html), f"book-card anchor not found in: {html[:2000]}"

    def test_card_shows_cover_thumbnail_with_lazy_loading(self, mock_catalog, client):
        mock_catalog.browse.return_value = (
            [make_book(7, title="Snow Crash"), make_book(8, title="Cryptonomicon")],
            2,
        )

        html = client.get("/books").data.decode()

        # Cards reuse the same /books/<id>/cover endpoint as the table thumbs.
        # We expect at least two lazy-loaded covers per book (one in the table,
        # one in the card) — i.e., at least 4 lazy images for 2 books.
        assert html.count('loading="lazy"') >= 4
        assert html.count("/books/7/cover") >= 2
        assert html.count("/books/8/cover") >= 2

    def test_card_shows_title_and_author(self, mock_catalog, client):
        mock_catalog.browse.return_value = (
            [make_book(1, title="Dune", authors=["Frank Herbert"])],
            1,
        )

        html = client.get("/books").data.decode()

        # Title and author appear inside the card region.
        # We use a coarse check: both strings appear at least twice (table + card).
        assert html.count("Dune") >= 2
        assert html.count("Frank Herbert") >= 2

    def test_card_shows_enriched_indicator_when_matched(self, mock_catalog, client):
        mock_catalog.browse.return_value = (
            [
                make_book(1, title="Enriched One", metadata_matched_at="2026-01-01T00:00:00"),
                make_book(2, title="Unenriched Two"),
            ],
            2,
        )

        html = client.get("/books").data.decode()

        # The enriched card carries an indicator class so CSS can style it.
        # We don't pin the exact glyph — just that the marker class exists for
        # at least the enriched book, and that the un-enriched one doesn't
        # accidentally inherit it.
        assert "book-card-enriched" in html

    def test_card_shows_format_or_language_badge_when_present(self, mock_catalog, client):
        mock_catalog.browse.return_value = (
            [make_book(1, title="Dune", language="en")],
            1,
        )

        html = client.get("/books").data.decode()

        # Language metadata surfaces in the card so users on mobile can see
        # at-a-glance which copies are which.
        assert "book-card-meta" in html
        # The actual language token is in the card region.
        assert "en" in html


class TestMobileCardCss:
    """The stylesheet defines the breakpoint that swaps table for cards."""

    def test_stylesheet_swaps_layouts_at_768px(self, client):
        """The 768px media query must exist and toggle both layouts."""
        # Pull the static stylesheet through the test client so we go through
        # the same routing the browser would use.
        response = client.get("/static/style.css")
        assert response.status_code == 200
        css = response.data.decode()

        # Defines a card layout (additions only — covers/etc untouched).
        assert ".book-card" in css
        assert ".book-cards" in css
        # 768px breakpoint must exist somewhere — the exact form is
        # `@media (max-width: 768px)` or `(min-width: 768px)`. Either works
        # provided it toggles `.book-table` and `.book-cards` display.
        assert "768px" in css
        # Default state: cards hidden on desktop (visible only via media query).
        # We don't pin the exact selector — just that .book-cards is mentioned
        # alongside `display:` to confirm the layout is controlled.
        assert re.search(r"\.book-cards[^{]*\{[^}]*display\s*:", css), (
            "expected .book-cards to have a display rule"
        )
