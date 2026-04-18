# ABOUTME: Unit tests for the tag-index builder — alphabetised, exclude/min-count filtering.
# ABOUTME: Also verifies the notes-without-tags report.

from pathlib import Path

from bookery.core.vault.index import build_tag_index
from bookery.core.vault.note import Note


def _note(title: str, tags: list[str], slug: str | None = None) -> Note:
    return Note(
        path=Path(f"{title}.md"),
        relative_folder="",
        title=title,
        slug=slug or title.lower().replace(" ", "-"),
        body="",
        frontmatter={},
        tags=tags,
    )


def test_alphabetises_tags_with_links():
    notes = [
        _note("A", ["zeta", "alpha"]),
        _note("B", ["alpha"]),
    ]
    result = build_tag_index(notes)
    assert "## alpha" in result.markdown
    assert result.markdown.index("## alpha") < result.markdown.index("## zeta")
    # Each tag's bullet links back via slug anchor.
    assert "[A](#a)" in result.markdown
    assert "[B](#b)" in result.markdown


def test_excludes_by_prefix():
    notes = [_note("A", ["type/note", "topic/x"])]
    result = build_tag_index(notes, exclude_prefixes=["type/"])
    assert "type/note" not in result.markdown
    assert "topic/x" in result.markdown


def test_min_count_filters_singletons():
    notes = [
        _note("A", ["rare"]),
        _note("B", ["common"]),
        _note("C", ["common"]),
    ]
    result = build_tag_index(notes, min_count=2)
    assert "rare" not in result.markdown
    assert "common" in result.markdown


def test_reports_notes_without_tags():
    notes = [_note("Tagged", ["x"]), _note("Untagged", [])]
    result = build_tag_index(notes)
    assert result.notes_without_tags == ["Untagged"]


def test_tag_appearing_under_multiple_notes():
    notes = [_note("A", ["shared"]), _note("B", ["shared"])]
    result = build_tag_index(notes)
    # Both notes listed under the single tag.
    tag_section = result.markdown.split("## shared", 1)[1]
    assert "[A](#a)" in tag_section
    assert "[B](#b)" in tag_section


def test_empty_index_has_header_only_markdown():
    notes = [_note("Untagged", [])]
    result = build_tag_index(notes)
    # No tag headings generated, but a top-level header should still appear.
    assert "# Tag Index" in result.markdown
    assert "## " not in result.markdown
