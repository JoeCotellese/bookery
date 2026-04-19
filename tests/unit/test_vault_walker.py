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


def test_exclude_tags_drops_notes_with_matching_frontmatter_tag(tmp_path: Path):
    _write(
        tmp_path / "meeting.md",
        "---\ntags:\n  - type/meeting\n  - nextgres\n---\n# Meeting\n",
    )
    _write(
        tmp_path / "idea.md",
        "---\ntags:\n  - type/permanent\n---\n# Idea\n",
    )
    _write(tmp_path / "untagged.md", "# Untagged\n")

    notes = walk_vault(tmp_path, exclude_tags=["type/meeting"])

    titles = sorted(n.title for n in notes)
    assert titles == ["Idea", "Untagged"]


def test_exclude_tags_empty_list_keeps_all_notes(tmp_path: Path):
    _write(tmp_path / "a.md", "---\ntags:\n  - foo\n---\n# A\n")
    _write(tmp_path / "b.md", "# B\n")

    notes = walk_vault(tmp_path, exclude_tags=[])

    assert sorted(n.title for n in notes) == ["A", "B"]


def test_exclude_tags_matches_any_of_several_excluded(tmp_path: Path):
    _write(tmp_path / "m.md", "---\ntags:\n  - type/meeting\n---\n# M\n")
    _write(tmp_path / "d.md", "---\ntags:\n  - type/daily\n---\n# D\n")
    _write(tmp_path / "p.md", "---\ntags:\n  - type/permanent\n---\n# P\n")

    notes = walk_vault(tmp_path, exclude_tags=["type/meeting", "type/daily"])

    assert [n.title for n in notes] == ["P"]


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


def test_on_progress_called_per_file(tmp_path: Path):
    for n in ["a.md", "b.md", "c.md"]:
        _write(tmp_path / n, f"# {n}\n")

    calls: list[tuple[int, int, str]] = []

    def cb(idx: int, total: int, path: Path) -> None:
        calls.append((idx, total, path.name))

    walk_vault(tmp_path, on_progress=cb)

    assert calls == [(1, 3, "a.md"), (2, 3, "b.md"), (3, 3, "c.md")]


def test_ordered_deterministically(tmp_path: Path):
    for name in ["c.md", "a.md", "b.md"]:
        _write(tmp_path / name, f"# {name}\n")

    notes = walk_vault(tmp_path)

    paths = [n.path.name for n in notes]
    assert paths == sorted(paths)
