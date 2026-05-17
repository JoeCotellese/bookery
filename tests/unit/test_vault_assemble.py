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
    # The folder is the chapter (H1); each note is a section (H2) under it.
    assert "# Perm {#folder-perm}" in result.markdown
    assert "## Note A {#note-a}" in result.markdown
    assert "## Note B {#note-b}" in result.markdown
    # Wiki-link resolved to the note slug.
    assert "[Note B](#note-b)" in result.markdown
    assert result.broken_link_count == 0


def test_folder_emitted_as_h1_chapter(tmp_path: Path):
    notes = [_note("Solo", "My Folder", "body")]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    assert "# My Folder {#folder-my-folder}" in md
    assert "## Solo {#solo}" in md
    # Folder header precedes the note section under it.
    assert md.index("# My Folder") < md.index("## Solo")


def test_root_folder_gets_label(tmp_path: Path):
    notes = [_note("Loose", "", "body")]
    result = assemble_vault(notes, vault_path=tmp_path)
    # Notes living at the vault root still need a chapter wrapper; use a
    # stable "Notes" label with a deterministic anchor.
    assert "# Notes {#folder-root}" in result.markdown
    assert "## Loose {#loose}" in result.markdown


def test_notes_alphabetized_within_folder(tmp_path: Path):
    notes = [
        _note("zeta", "F", "z"),
        _note("Alpha", "F", "a"),
        _note("mango", "F", "m"),
    ]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    # Case-insensitive A→Z within a folder.
    assert md.index("## Alpha") < md.index("## mango") < md.index("## zeta")


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
    md = result.markdown
    # Folders are sorted; each folder H1 precedes its notes' H2 sections.
    assert md.index("# Lit") < md.index("## B")
    assert md.index("# Perm") < md.index("## A")
    assert md.index("# Lit") < md.index("# Perm")


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


def test_body_h1_demoted_to_h3(tmp_path: Path):
    # Folders are H1, notes are H2. A body H1 must drop two levels to H3 so
    # pandoc's --toc-depth=2 never picks it up as a chapter or section.
    notes = [_note("Same Title", "F", "![cover](x.png)\n\n# Same Title\n\nbody\n")]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    # Exactly one H1 per folder.
    h1_lines = [ln for ln in md.splitlines() if ln.startswith("# ")]
    assert h1_lines == ["# F {#folder-f}"]
    # Note heading is H2; body H1 demoted to H3.
    assert "## Same Title {#same-title}" in md
    assert "### Same Title" in md


def test_non_matching_body_h1_also_demoted(tmp_path: Path):
    notes = [_note("Title", "F", "# Different Heading\n\nbody\n")]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    h1_lines = [ln for ln in md.splitlines() if ln.startswith("# ")]
    assert h1_lines == ["# F {#folder-f}"]
    assert "### Different Heading" in md


def test_body_h2_demoted_to_h4(tmp_path: Path):
    # The note itself owns H2; any in-body H2 must cascade down to H4 to keep
    # the TOC clean and the heading hierarchy consistent.
    notes = [_note("T", "F", "## Subsection\n\nbody\n")]
    result = assemble_vault(notes, vault_path=tmp_path)
    md = result.markdown
    # Only one H2 per note: the note's own heading.
    h2_lines = [ln for ln in md.splitlines() if ln.startswith("## ")]
    assert h2_lines == ["## T {#t}"]
    assert "#### Subsection" in md


def test_duplicate_titles_in_same_folder_use_filename_hint(tmp_path: Path):
    # Two "Reference" literature notes in the same folder — common in a real
    # vault where every book note has its own References.md. The folder alone
    # cannot disambiguate them, so fall back to the filename stem.
    n1 = Note(
        path=Path("book-a-references.md"),
        relative_folder="Lit",
        title="Reference",
        slug="reference",
        body="a",
        frontmatter={},
        tags=[],
    )
    n2 = Note(
        path=Path("book-b-references.md"),
        relative_folder="Lit",
        title="Reference",
        slug="reference",
        body="b",
        frontmatter={},
        tags=[],
    )
    result = assemble_vault([n1, n2], vault_path=tmp_path)
    md = result.markdown
    assert "## Reference (book-a-references)" in md
    assert "## Reference (book-b-references)" in md


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
