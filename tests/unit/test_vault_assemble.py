# ABOUTME: Unit tests for the vault assembler — concat + link resolution + folder grouping.
# ABOUTME: Verifies the title-slug map is built across all notes before per-note resolution.

from pathlib import Path

from bookery.core.vault.assemble import AssembledVault, assemble_vault
from bookery.core.vault.note import Note


def _note(title: str, folder: str, body: str, tags: list[str] | None = None) -> Note:
    return Note(
        path=Path(f"{folder}/{title}.md"),
        relative_folder=folder,
        title=title,
        slug=title.lower().replace(" ", "-"),
        body=body,
        frontmatter={},
        tags=tags or [],
    )


def test_assembles_concatenated_markdown_with_anchors(tmp_path: Path):
    notes = [
        _note("Note A", "Perm", "Body A linking to [[Note B]]."),
        _note("Note B", "Perm", "Body B."),
    ]
    result = assemble_vault(notes, vault_path=tmp_path)

    assert isinstance(result, AssembledVault)
    # Each note produces an H1 with an anchor via {#slug}.
    assert "# Note A {#note-a}" in result.markdown
    assert "# Note B {#note-b}" in result.markdown
    # Wiki-link resolved.
    assert "[Note B](#note-b)" in result.markdown
    assert result.broken_link_count == 0


def test_broken_link_counted(tmp_path: Path):
    notes = [_note("Solo", "P", "See [[Missing]].")]
    result = assemble_vault(notes, vault_path=tmp_path)
    assert "*Missing*" in result.markdown
    assert result.broken_link_count == 1


def test_folder_grouping_headers(tmp_path: Path):
    notes = [
        _note("A", "Perm", "a"),
        _note("B", "Lit", "b"),
    ]
    result = assemble_vault(notes, vault_path=tmp_path)
    # Folder names appear as top-level section separators before their notes.
    assert result.markdown.index("Lit") < result.markdown.index("# B")
    assert result.markdown.index("Perm") < result.markdown.index("# A")


def test_index_appended_when_enabled(tmp_path: Path):
    notes = [_note("A", "P", "a", tags=["topic"])]
    result = assemble_vault(notes, vault_path=tmp_path, include_index=True)
    assert "# Tag Index" in result.markdown
    assert "## topic" in result.markdown


def test_on_progress_called_per_note(tmp_path: Path):
    notes = [_note("A", "F", "a"), _note("B", "F", "b"), _note("C", "F", "c")]
    seen: list[tuple[int, int, str]] = []

    def cb(idx: int, total: int, title: str) -> None:
        seen.append((idx, total, title))

    assemble_vault(notes, vault_path=tmp_path, on_progress=cb)

    assert [(i, t) for i, t, _ in seen] == [(1, 3), (2, 3), (3, 3)]
    assert sorted(title for _, _, title in seen) == ["A", "B", "C"]


def test_body_h1_demoted_to_h2(tmp_path: Path):
    # Any H1 in the body — matching or not, at the start or buried after
    # other content — must be demoted so pandoc's --toc-depth=1 never picks
    # it up as a sibling chapter.
    notes = [_note("Same Title", "F", "![cover](x.png)\n\n# Same Title\n\nbody\n")]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    # Exactly one top-level heading per note: the assembler's anchor-bearing H1.
    h1_lines = [ln for ln in md.splitlines() if ln.startswith("# ")]
    assert h1_lines == ["# Same Title {#same-title}"]
    h2_lines = [ln for ln in md.splitlines() if ln.startswith("## ")]
    assert "## Same Title" in h2_lines


def test_non_matching_body_h1_also_demoted(tmp_path: Path):
    notes = [_note("Title", "F", "# Different Heading\n\nbody\n")]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    h1_lines = [ln for ln in md.splitlines() if ln.startswith("# ")]
    assert h1_lines == ["# Title {#title}"]
    assert "## Different Heading" in md


def test_duplicate_titles_get_unique_slugs(tmp_path: Path):
    # Two separate notes both titled "References" — e.g. a per-book refs note
    # repeated across many book notes in a real vault.
    notes = [
        _note("References", "Book A", "a refs"),
        _note("References", "Book B", "b refs"),
    ]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    # Anchors must be unique so pandoc produces a valid EPUB.
    assert md.count("{#references}") == 1
    assert "{#references-2}" in md
    # Display titles should include a folder hint so readers can tell them apart.
    assert "References (Book A)" in md
    assert "References (Book B)" in md


def test_notes_without_tags_reported(tmp_path: Path):
    notes = [_note("Tagged", "P", "x", tags=["t"]), _note("Untagged", "P", "y")]
    result = assemble_vault(notes, vault_path=tmp_path, include_index=True)
    assert "Untagged" in result.notes_without_tags
