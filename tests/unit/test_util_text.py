# ABOUTME: Unit tests for the description text helpers — strip_html and description_paragraphs.
# ABOUTME: Covers tag removal, entity decoding, paragraph preservation, and Jinja-safe HTML output.

from markupsafe import Markup

from bookery.util.text import description_paragraphs, strip_html


class TestStripHtml:
    def test_returns_empty_for_empty_input(self):
        assert strip_html("") == ""

    def test_passes_plain_text_through_unchanged(self):
        assert strip_html("Just a sentence.") == "Just a sentence."

    def test_strips_simple_tags(self):
        assert strip_html("<p>hello</p>") == "hello"

    def test_strips_attributes_inside_tags(self):
        assert strip_html('<p class="description">hello</p>') == "hello"

    def test_decodes_html_entities(self):
        assert strip_html("foo &amp; bar") == "foo & bar"

    def test_decodes_numeric_entities(self):
        assert strip_html("don&#x27;t") == "don't"

    def test_preserves_paragraph_breaks(self):
        html = "<p>first</p><p>second</p>"
        assert strip_html(html) == "first\n\nsecond"

    def test_blank_line_separated_text_preserved(self):
        text = "paragraph one\n\nparagraph two"
        assert strip_html(text) == "paragraph one\n\nparagraph two"

    def test_collapses_runs_of_inline_whitespace(self):
        assert strip_html("foo    bar\tbaz") == "foo bar baz"

    def test_br_becomes_newline(self):
        # <br> is a line break, not a paragraph break — gets normalized to a
        # space in single-paragraph context but doesn't run words together.
        assert strip_html("line one<br>line two") == "line one line two"

    def test_idempotent_on_plain_text(self):
        text = "first paragraph\n\nsecond paragraph"
        once = strip_html(text)
        twice = strip_html(once)
        assert once == twice

    def test_idempotent_on_html_input(self):
        html = "<p>first</p><p>second &amp; third</p>"
        once = strip_html(html)
        twice = strip_html(once)
        assert once == twice
        assert once == "first\n\nsecond & third"

    def test_nested_tags_stripped(self):
        assert strip_html("<div><p><em>hi</em></p></div>") == "hi"

    def test_drops_empty_paragraphs(self):
        # Multiple blank lines collapse to a single paragraph break and any
        # all-whitespace "paragraphs" get dropped.
        assert strip_html("a\n\n\n\nb") == "a\n\nb"

    def test_strips_book_524_repro_case(self):
        # Mirrors the reported bug: stored description contains a literal
        # <p class="description"> wrapper. After strip we want plain prose.
        raw = '<p class="description">A great story about &amp;c.</p>'
        assert strip_html(raw) == "A great story about &c."


class TestDescriptionParagraphs:
    def test_returns_empty_markup_for_none(self):
        result = description_paragraphs(None)
        assert isinstance(result, Markup)
        assert str(result) == ""

    def test_returns_empty_markup_for_empty_string(self):
        assert str(description_paragraphs("")) == ""

    def test_wraps_single_paragraph_in_p(self):
        assert str(description_paragraphs("hello")) == "<p>hello</p>"

    def test_wraps_multiple_paragraphs(self):
        result = str(description_paragraphs("first\n\nsecond"))
        assert "<p>first</p>" in result
        assert "<p>second</p>" in result

    def test_escapes_special_chars(self):
        # Plain-text storage may still contain raw "&" or "<"; render-time
        # must escape so the browser shows them literally.
        result = str(description_paragraphs("a & b"))
        assert result == "<p>a &amp; b</p>"

    def test_does_not_double_escape_existing_entities(self):
        # Storage is plain text, so "&" is just an ampersand — not an entity.
        # Escape it once at render.
        result = str(description_paragraphs("&amp;"))
        assert result == "<p>&amp;amp;</p>"
