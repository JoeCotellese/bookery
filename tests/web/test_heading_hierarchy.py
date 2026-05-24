# ABOUTME: Plan-01 step 7 — heading hierarchy semantics tests (issue #126).
# ABOUTME: Asserts one H1 per page, no heading-level skips, site name not a heading.

from html.parser import HTMLParser

import pytest

from tests.web.conftest import make_book


class HeadingCollector(HTMLParser):
    """Collect headings (level + text) and `.logo` anchor presence in document order.

    Uses only the stdlib to avoid adding a new dependency just for these tests.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.headings: list[tuple[int, str]] = []  # (level, text)
        self.logo_texts: list[str] = []
        self._stack: list[tuple[str, dict[str, str]]] = []
        self._heading_buf: list[str] = []
        self._logo_buf: list[str] = []

    @staticmethod
    def _heading_level(tag: str) -> int | None:
        if len(tag) == 2 and tag[0] == "h" and tag[1].isdigit():
            n = int(tag[1])
            if 1 <= n <= 6:
                return n
        return None

    def handle_starttag(self, tag, attrs):
        attrs_d = {k: (v or "") for k, v in attrs}
        self._stack.append((tag, attrs_d))
        if tag == "a" and "logo" in attrs_d.get("class", "").split():
            self._logo_buf = []

    def handle_endtag(self, tag):
        # Pop matching tag (most recent occurrence) — templates here are
        # well-formed enough that a simple pop is safe.
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                _, attrs_d = self._stack.pop(i)
                if tag == "a" and "logo" in attrs_d.get("class", "").split():
                    self.logo_texts.append("".join(self._logo_buf).strip())
                    self._logo_buf = []
                if self._heading_level(tag) is not None:
                    level = self._heading_level(tag)
                    assert level is not None  # for type-checker
                    text = "".join(self._heading_buf).strip()
                    self.headings.append((level, text))
                    self._heading_buf = []
                break

    def handle_data(self, data):
        # Collect text for any currently-open heading or logo anchor.
        inside_heading = any(self._heading_level(t) is not None for t, _ in self._stack)
        if inside_heading:
            self._heading_buf.append(data)
        for t, a in self._stack:
            if t == "a" and "logo" in a.get("class", "").split():
                self._logo_buf.append(data)
                break


def collect(html: str) -> HeadingCollector:
    p = HeadingCollector()
    p.feed(html)
    return p


def assert_no_level_skips(headings: list[tuple[int, str]]) -> None:
    """Allow same or smaller jumps; forbid increases of more than +1."""
    prev = 0
    for level, text in headings:
        if prev == 0:
            assert level == 1, f"First heading must be H1, got H{level} ({text!r})"
        else:
            assert level <= prev + 1, (
                f"Heading skip: H{prev} -> H{level} ({text!r}); full sequence: {headings}"
            )
        prev = level


class TestLogoIsNotHeading:
    """Site name "Bookery" is an `<a class=logo>`, not a heading element."""

    def test_list_page_logo_is_anchor_not_heading(self, mock_catalog, client):
        mock_catalog.browse.return_value = ([], 0)
        html = client.get("/books").data.decode()
        p = collect(html)
        # No heading should contain just the site brand text.
        assert all("Bookery" not in t or level != 1 or t != "Bookery" for level, t in p.headings)
        # Logo anchor present with brand text.
        assert "Bookery" in p.logo_texts, (
            f"Expected an <a class=logo>Bookery</a>; "
            f"got logos={p.logo_texts}, headings={p.headings}"
        )

    def test_detail_page_logo_is_anchor_not_heading(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1, title="Dune", authors=["Frank Herbert"])
        html = client.get("/books/1").data.decode()
        p = collect(html)
        assert "Bookery" in p.logo_texts


class TestExactlyOneH1:
    def test_list_page_has_one_h1_library(self, mock_catalog, client):
        mock_catalog.browse.return_value = ([], 0)
        html = client.get("/books").data.decode()
        p = collect(html)
        h1s = [t for level, t in p.headings if level == 1]
        assert h1s == ["Library"], f"Expected exactly one H1 'Library', got {h1s}"

    def test_detail_page_h1_is_book_title(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1, title="Dune", authors=["Frank Herbert"])
        html = client.get("/books/1").data.decode()
        p = collect(html)
        h1s = [t for level, t in p.headings if level == 1]
        assert h1s == ["Dune"], f"Expected exactly one H1 'Dune', got {h1s}"

    def test_edit_partial_h1_is_edit_title(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1, title="Dune")
        html = client.get("/books/1/edit").data.decode()
        p = collect(html)
        h1s = [t for level, t in p.headings if level == 1]
        assert h1s == ["Edit: Dune"], f"Expected exactly one H1 'Edit: Dune', got {h1s}"


class TestNoHeadingLevelSkips:
    def test_list_page_no_skips(self, mock_catalog, client):
        mock_catalog.browse.return_value = ([], 0)
        html = client.get("/books").data.decode()
        p = collect(html)
        assert_no_level_skips(p.headings)

    def test_detail_page_no_skips_minimal(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1, title="Dune")
        html = client.get("/books/1").data.decode()
        p = collect(html)
        assert_no_level_skips(p.headings)

    def test_detail_page_no_skips_with_tags_and_genres(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(
            1, title="Dune", isbn="9780441172719", series="Dune Chronicles"
        )
        mock_catalog.get_tags_for_book.return_value = ["sci-fi", "classic"]
        mock_catalog.get_genres_for_book.return_value = [("Science Fiction", True)]
        html = client.get("/books/1").data.decode()
        p = collect(html)
        assert_no_level_skips(p.headings)

    def test_edit_partial_no_skips(self, mock_catalog, client):
        mock_catalog.get_by_id.return_value = make_book(1, title="Dune")
        html = client.get("/books/1/edit").data.decode()
        p = collect(html)
        # Edit form is an HTMX partial — in its own context the H1 must
        # be first and downstream headings must not skip levels.
        assert_no_level_skips(p.headings)


class TestSectionHeadingsAreH2:
    """Detail section headings drop to H2 once the book title is H1."""

    @pytest.mark.parametrize(
        "section_text",
        ["Identity", "Publication", "Classification", "File", "Description"],
    )
    def test_section_heading_is_h2_when_present(self, mock_catalog, client, section_text):
        mock_catalog.get_by_id.return_value = make_book(
            1,
            title="Dune",
            isbn="9780441172719",
            language="en",
            publisher="Ace",
            description="A novel.",
        )
        mock_catalog.get_tags_for_book.return_value = ["sci-fi"]
        html = client.get("/books/1").data.decode()
        p = collect(html)
        matching = [level for level, text in p.headings if text == section_text]
        assert matching, f"Expected a heading {section_text!r} on detail page"
        assert all(level == 2 for level in matching), (
            f"Expected {section_text!r} to be H2, got levels {matching}"
        )
