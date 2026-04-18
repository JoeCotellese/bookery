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
