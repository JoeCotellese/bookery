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


def test_notes_without_tags_reported(tmp_path: Path):
    notes = [_note("Tagged", "P", "x", tags=["t"]), _note("Untagged", "P", "y")]
    result = assemble_vault(notes, vault_path=tmp_path, include_index=True)
    assert "Untagged" in result.notes_without_tags
