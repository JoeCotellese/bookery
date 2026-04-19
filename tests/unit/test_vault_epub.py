# ABOUTME: Unit tests for the pandoc-based EPUB render wrapper.
# ABOUTME: Skips when pandoc is not on PATH; asserts identifier plumbed through.

import shutil
from pathlib import Path

import pytest
from ebooklib import epub

from bookery.core.vault.epub import EpubMetadata, PandocMissingError, render_epub, stable_uuid

pandoc_required = pytest.mark.skipif(
    shutil.which("pandoc") is None, reason="pandoc not installed"
)


def test_pandoc_missing_raises(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(PandocMissingError):
        render_epub(
            "x",
            [],
            EpubMetadata(title="T", author="A", identifier=stable_uuid(tmp_path)),
            tmp_path / "x.epub",
        )


def test_render_disables_multiline_tables_extension(monkeypatch, tmp_path: Path):
    """Pandoc's ``multiline_tables`` extension greedily consumes H1 headings as
    table rows whenever a note body contains a ``---`` thematic break, dropping
    hundreds of chapters from large vault exports and leaving cross-note links
    as bare ``#slug`` fragments that never navigate. The extension must be
    disabled via the input format spec.
    """
    captured: dict[str, list[str]] = {}

    class _Result:
        returncode = 0
        stderr = ""

    def _fake_run(cmd, capture_output, text, cwd):
        captured["cmd"] = cmd
        # Produce an empty file so downstream code does not blow up.
        out_idx = cmd.index("-o") + 1
        Path(cmd[out_idx]).write_bytes(b"")
        return _Result()

    import subprocess

    monkeypatch.setattr(subprocess, "run", _fake_run)
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/pandoc")
    render_epub(
        "# One {#one}\n",
        [],
        EpubMetadata(title="T", author="A", identifier=stable_uuid(tmp_path)),
        tmp_path / "x.epub",
    )
    fmt = captured["cmd"][captured["cmd"].index("-f") + 1]
    assert "-multiline_tables" in fmt, (
        f"expected multiline_tables extension to be disabled; got -f {fmt!r}"
    )


@pandoc_required
def test_render_produces_epub_with_identifier(tmp_path: Path):
    out = tmp_path / "v.epub"
    ident = stable_uuid(tmp_path)
    render_epub(
        "# One {#one}\n\ncontent\n\n# Two {#two}\n\nlink [One](#one)\n",
        [],
        EpubMetadata(title="My Vault", author="Me", identifier=ident, version_label="2026-04-18"),
        out,
    )
    assert out.exists() and out.stat().st_size > 0
    book = epub.read_epub(str(out))
    # The identifier set via --metadata should be recoverable from the OPF.
    identifiers = book.get_metadata("DC", "identifier")
    flattened = [v for v, _ in identifiers]
    assert any(ident in v for v in flattened)
