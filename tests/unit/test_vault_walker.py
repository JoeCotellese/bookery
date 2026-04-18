# ABOUTME: Unit tests for the vault walker — folder filtering, markdown discovery, ordering.
# ABOUTME: Uses tmp_path to build a small vault on disk for each test.

from pathlib import Path

from bookery.core.vault.walker import walk_vault


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_walks_entire_vault_when_no_folders(tmp_path: Path):
    _write(tmp_path / "a.md", "# A\n")
    _write(tmp_path / "sub/b.md", "---\ntitle: B\n---\nbody")
    _write(tmp_path / "sub/nested/c.md", "# C-heading\n")

    notes = walk_vault(tmp_path)

    titles = sorted(n.title for n in notes)
    assert titles == ["A", "B", "C-heading"]


def test_folder_whitelist_filters_other_dirs(tmp_path: Path):
    _write(tmp_path / "Permanent/x.md", "# X\n")
    _write(tmp_path / "Literature/y.md", "# Y\n")
    _write(tmp_path / "Daily/z.md", "# Z\n")

    notes = walk_vault(tmp_path, folders=["Permanent", "Literature"])

    titles = sorted(n.title for n in notes)
    assert titles == ["X", "Y"]


def test_skips_hidden_and_non_markdown(tmp_path: Path):
    _write(tmp_path / ".obsidian/config.json", "{}")
    _write(tmp_path / "note.md", "# N\n")
    _write(tmp_path / "image.png", "binary")
    _write(tmp_path / ".hidden.md", "# hidden\n")

    notes = walk_vault(tmp_path)

    assert [n.title for n in notes] == ["N"]


def test_relative_folder_recorded(tmp_path: Path):
    _write(tmp_path / "Permanent/note.md", "# N\n")

    notes = walk_vault(tmp_path)

    assert notes[0].relative_folder == "Permanent"


def test_root_level_note_has_empty_relative_folder(tmp_path: Path):
    _write(tmp_path / "top.md", "# T\n")

    notes = walk_vault(tmp_path)

    assert notes[0].relative_folder == ""


def test_note_body_has_frontmatter_stripped(tmp_path: Path):
    _write(tmp_path / "n.md", "---\ntitle: N\ntags: [x]\n---\nbody text")

    notes = walk_vault(tmp_path)

    assert notes[0].body == "body text"
    assert notes[0].tags == ["x"]


def test_ordered_deterministically(tmp_path: Path):
    for name in ["c.md", "a.md", "b.md"]:
        _write(tmp_path / name, f"# {name}\n")

    notes = walk_vault(tmp_path)

    paths = [n.path.name for n in notes]
    assert paths == sorted(paths)
