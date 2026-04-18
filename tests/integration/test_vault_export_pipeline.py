# ABOUTME: Integration tests for the full vault export pipeline up to pandoc-ready markdown.
# ABOUTME: Uses the tests/fixtures/vault tree with cross-links, a broken link, and an image.

from pathlib import Path

from bookery.core.vault.assemble import assemble_vault
from bookery.core.vault.walker import walk_vault

FIXTURE = Path(__file__).parent.parent / "fixtures" / "vault"


def test_full_pipeline_produces_expected_markdown():
    notes = walk_vault(FIXTURE)
    titles = sorted(n.title for n in notes)
    assert titles == ["Lit One", "Note A", "Note B"]

    result = assemble_vault(notes, vault_path=FIXTURE, include_index=True)
    md = result.markdown

    # Anchors present.
    assert "# Note A {#note-a}" in md
    assert "# Note B {#note-b}" in md
    assert "# Lit One {#lit-one}" in md

    # Resolved wiki-links.
    assert "[Note B](#note-b)" in md
    assert "[Note A](#note-a)" in md

    # Broken links counted (Note A → Missing Target, Note B → Does Not Exist).
    assert result.broken_link_count == 2
    assert "*Missing Target*" in md
    assert "*dangling*" in md

    # Image resolved.
    assert "![sample.png](sample.png)" in md
    assert any(p.name == "sample.png" for p in result.asset_paths)

    # Tag index present with shared tag linking all three notes.
    assert "# Tag Index" in md
    assert "## shared" in md


def test_folder_filter_excludes_other_folders():
    notes = walk_vault(FIXTURE, folders=["3_Permanent Notes"])
    titles = sorted(n.title for n in notes)
    assert titles == ["Note A", "Note B"]


def test_index_exclude_prefix_filters_topic():
    notes = walk_vault(FIXTURE)
    result = assemble_vault(
        notes,
        vault_path=FIXTURE,
        include_index=True,
        index_exclude_prefixes=["topic/"],
    )
    assert "topic/" not in result.markdown
    assert "## shared" in result.markdown
