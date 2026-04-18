# ABOUTME: Unit tests for image resolution — Obsidian `![[asset]]` and standard `![alt](path)`.
# ABOUTME: Verifies path resolution, asset collection, and rewriting to pandoc-friendly form.

from pathlib import Path

from bookery.core.vault.image import build_asset_index, resolve_images


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x89PNG fake")


def test_resolves_obsidian_embed(tmp_path: Path):
    img = tmp_path / "assets" / "sample.png"
    _touch(img)
    index = build_asset_index(tmp_path)

    body = "Before\n\n![[sample.png]]\n\nAfter"
    out, assets = resolve_images(body, note_path=tmp_path / "a.md", asset_index=index)

    assert "![sample.png](sample.png)" in out
    assert [a.resolve() for a in assets] == [img.resolve()]


def test_embed_with_missing_asset_left_as_italic(tmp_path: Path):
    body = "text ![[missing.png]] tail"
    index: dict[str, Path] = {}
    out, assets = resolve_images(body, note_path=tmp_path / "a.md", asset_index=index)
    assert "*missing.png*" in out
    assert assets == []


def test_standard_markdown_image_resolved_relative(tmp_path: Path):
    img = tmp_path / "dir" / "pic.png"
    _touch(img)
    index = build_asset_index(tmp_path)

    body = "![alt](dir/pic.png)"
    out, assets = resolve_images(body, note_path=tmp_path / "note.md", asset_index=index)
    assert "![alt](pic.png)" in out
    assert [a.resolve() for a in assets] == [img.resolve()]


def test_absolute_and_remote_images_untouched(tmp_path: Path):
    body = "![x](http://example.com/y.png) and ![z](/abs/path.png)"
    out, assets = resolve_images(
        body, note_path=tmp_path / "n.md", asset_index=build_asset_index(tmp_path)
    )
    assert "http://example.com/y.png" in out
    assert assets == []


def test_build_asset_index_maps_by_filename(tmp_path: Path):
    a = tmp_path / "x" / "foo.png"
    b = tmp_path / "y" / "bar.jpg"
    _touch(a)
    _touch(b)
    idx = build_asset_index(tmp_path)
    assert idx["foo.png"].resolve() == a.resolve()
    assert idx["bar.jpg"].resolve() == b.resolve()
