# ABOUTME: Unit tests for _pdf_support helpers — capture match output paths, place kepubs.

from pathlib import Path
from typing import Any

from rich.console import Console

from bookery.cli._pdf_support import (
    PdfPair,
    place_kepubs_alongside_epubs,
    wrap_match_fn_capturing_paths,
)
from bookery.core.importer import MatchResult
from bookery.metadata.types import BookMetadata


def _metadata() -> BookMetadata:
    return BookMetadata(title="T", authors=["A"])


def test_wrap_none_returns_none() -> None:
    wrapped, captured = wrap_match_fn_capturing_paths(None)
    assert wrapped is None
    assert captured == {}


def test_wrap_captures_output_paths(tmp_path: Path) -> None:
    epub = tmp_path / "a.epub"
    dest = tmp_path / "library" / "A" / "T" / "a.epub"

    def fake_match(_meta: BookMetadata, _path: Path) -> MatchResult:
        return MatchResult(metadata=_metadata(), output_path=dest)

    wrapped, captured = wrap_match_fn_capturing_paths(fake_match)
    assert wrapped is not None
    wrapped(_metadata(), epub)
    assert captured[epub] == dest


def test_wrap_skips_when_match_returns_none() -> None:
    def fake_match(_meta: BookMetadata, _path: Path) -> MatchResult | None:
        return None

    wrapped, captured = wrap_match_fn_capturing_paths(fake_match)
    assert wrapped is not None
    wrapped(_metadata(), Path("/tmp/x.epub"))
    assert captured == {}


def test_place_kepubs_copies_to_dest_dir(tmp_path: Path) -> None:
    epub = tmp_path / "tmp" / "book.epub"
    epub.parent.mkdir()
    epub.write_bytes(b"epub")
    kepub = tmp_path / "tmp" / "book.kepub.epub"
    kepub.write_bytes(b"kepub")
    dest_epub = tmp_path / "library" / "A" / "T" / "book.epub"
    dest_epub.parent.mkdir(parents=True)
    dest_epub.write_bytes(b"epub")

    pair = PdfPair(source=tmp_path / "book.pdf", epub=epub, kepub=kepub)
    captured = {epub: dest_epub}
    console = Console(file=Path.open(tmp_path / "log.txt", "w"), force_terminal=False)
    place_kepubs_alongside_epubs([pair], captured, console)

    assert (dest_epub.parent / "book.kepub.epub").exists()


def test_place_kepubs_warns_on_missing_output(tmp_path: Path) -> None:
    epub = tmp_path / "tmp" / "book.epub"
    epub.parent.mkdir()
    epub.write_bytes(b"epub")
    kepub = tmp_path / "tmp" / "book.kepub.epub"
    kepub.write_bytes(b"kepub")

    pair = PdfPair(source=tmp_path / "book.pdf", epub=epub, kepub=kepub)
    log_path = tmp_path / "log.txt"
    console = Console(file=Path.open(log_path, "w"), force_terminal=False)
    place_kepubs_alongside_epubs([pair], {}, console)

    console.file.close()
    log = log_path.read_text()
    assert "warning" in log.lower()
    assert "book.pdf" in log


def test_pdf_pair_is_frozen() -> None:
    import dataclasses

    pair = PdfPair(source=Path("/a"), epub=Path("/b"), kepub=Path("/c"))
    try:
        pair.source = Path("/z")  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("PdfPair should be frozen")


_ = Any  # keep Any alias reachable
