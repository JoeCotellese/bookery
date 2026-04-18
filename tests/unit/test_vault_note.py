# ABOUTME: Unit tests for vault Note dataclass, slugify, and title resolution.
# ABOUTME: Covers deterministic slugging and the frontmatter → H1 → filename fallback.

from pathlib import Path

from bookery.core.vault.note import Note, resolve_title, slugify


class TestSlugify:
    def test_lowercases_and_hyphenates(self):
        assert slugify("Hello World") == "hello-world"

    def test_strips_punctuation(self):
        assert slugify("What is X? A note!") == "what-is-x-a-note"

    def test_collapses_repeated_separators(self):
        assert slugify("a--b  c") == "a-b-c"

    def test_preserves_hierarchical_slash_as_hyphen(self):
        assert slugify("type/note") == "type-note"

    def test_deterministic(self):
        assert slugify("Same Title") == slugify("Same Title")

    def test_unicode_collapses_to_ascii(self):
        # Accented chars collapse to ascii or hyphens; assert non-empty + lowercase.
        out = slugify("Café Résumé")
        assert out and out == out.lower()
        assert " " not in out


class TestResolveTitle:
    def test_frontmatter_title_wins(self):
        title = resolve_title(
            frontmatter_title="FM Title",
            body="# H1 Title\n\ncontent",
            path=Path("20240101-my-file.md"),
        )
        assert title == "FM Title"

    def test_first_h1_when_no_frontmatter(self):
        title = resolve_title(
            frontmatter_title=None,
            body="intro\n\n# Real Heading\n\nbody",
            path=Path("foo.md"),
        )
        assert title == "Real Heading"

    def test_filename_fallback_strips_suffix(self):
        title = resolve_title(
            frontmatter_title=None,
            body="no heading here",
            path=Path("my-note.md"),
        )
        assert title == "my-note"

    def test_filename_fallback_strips_timestamp_prefix(self):
        title = resolve_title(
            frontmatter_title=None,
            body="no heading",
            path=Path("20240315-atomic-habits.md"),
        )
        assert title == "atomic-habits"

    def test_empty_frontmatter_title_ignored(self):
        title = resolve_title(
            frontmatter_title="   ",
            body="# Real",
            path=Path("x.md"),
        )
        assert title == "Real"


class TestNote:
    def test_note_is_a_dataclass_with_expected_fields(self):
        n = Note(
            path=Path("a.md"),
            relative_folder="Notes",
            title="A",
            slug="a",
            body="body",
            frontmatter={},
            tags=[],
        )
        assert n.title == "A"
        assert n.slug == "a"
        assert n.tags == []
