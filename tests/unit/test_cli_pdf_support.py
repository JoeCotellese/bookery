# ABOUTME: Unit tests for _pdf_support helpers — hash snapshot + catalog-based kepub placement.

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from rich.console import Console

from bookery.cli._pdf_support import (
    PdfPair,
    place_kepubs_via_catalog,
    snapshot_epub_hashes,
)
from bookery.db.hashing import compute_file_hash


def test_pdf_pair_is_frozen() -> None:
    import dataclasses

    pair = PdfPair(source=Path("/a"), epub=Path("/b"), kepub=Path("/c"))
    try:
        pair.source = Path("/z")  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("PdfPair should be frozen")


def test_snapshot_epub_hashes(tmp_path: Path) -> None:
    epub = tmp_path / "book.epub"
    epub.write_bytes(b"epub contents")
    pair = PdfPair(source=tmp_path / "src.pdf", epub=epub, kepub=tmp_path / "k.kepub.epub")

    hashes = snapshot_epub_hashes([pair])
    assert hashes[epub] == compute_file_hash(epub)


def test_place_kepubs_copies_to_cataloged_dir(tmp_path: Path) -> None:
    epub = tmp_path / "tmp" / "book.epub"
    epub.parent.mkdir()
    epub.write_bytes(b"epub")
    kepub = tmp_path / "tmp" / "book.kepub.epub"
    kepub.write_bytes(b"kepub")

    dest_epub = tmp_path / "library" / "Unknown" / "Title" / "book.epub"
    dest_epub.parent.mkdir(parents=True)
    dest_epub.write_bytes(b"epub")

    pair = PdfPair(source=tmp_path / "src.pdf", epub=epub, kepub=kepub)
    hashes = {epub: "h1"}

    catalog = MagicMock()
    record: Any = MagicMock()
    record.output_path = dest_epub
    catalog.get_by_hash.return_value = record

    log = tmp_path / "log.txt"
    console = Console(file=Path.open(log, "w"), force_terminal=False)
    place_kepubs_via_catalog([pair], hashes, catalog, console)
    console.file.close()

    assert (dest_epub.parent / "book.kepub.epub").exists()
    catalog.get_by_hash.assert_called_once_with("h1")


def test_place_kepubs_warns_when_not_cataloged(tmp_path: Path) -> None:
    epub = tmp_path / "tmp" / "book.epub"
    epub.parent.mkdir()
    epub.write_bytes(b"epub")
    kepub = tmp_path / "tmp" / "book.kepub.epub"
    kepub.write_bytes(b"kepub")

    pair = PdfPair(source=tmp_path / "src.pdf", epub=epub, kepub=kepub)
    catalog = MagicMock()
    catalog.get_by_hash.return_value = None

    log = tmp_path / "log.txt"
    console = Console(file=Path.open(log, "w"), force_terminal=False)
    place_kepubs_via_catalog([pair], {epub: "h"}, catalog, console)
    console.file.close()

    text = log.read_text()
    assert "warning" in text.lower()
    assert "src.pdf" in text
