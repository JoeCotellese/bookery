# ABOUTME: Acceptance test for #312: AZW/AZW3 support in add, convert, and info.
# ABOUTME: Drives the CLI against a real DRM-free Gutenberg AZW3 and a DRM-flagged copy.

import re
import shutil
import struct
from pathlib import Path

import pytest
from click.testing import CliRunner
from ebooklib import epub

from bookery.cli import cli

FIXTURE = Path(__file__).parent.parent / "fixtures" / "kindle" / "alice.azw3"
TITLE = "Alice's Adventures in Wonderland"
DRM_MESSAGE = "is DRM-protected; bookery only reads DRM-free files"


def _copy(dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURE, dest)
    return dest


def _drm_copy(dest: Path) -> Path:
    """Copy the fixture and set the MOBI header crypto_type (record 0, +0x0C) non-zero."""
    data = bytearray(FIXTURE.read_bytes())
    record0 = struct.unpack_from(">I", data, 78)[0]
    struct.pack_into(">H", data, record0 + 0x0C, 2)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def _write_epub(dest: Path) -> None:
    book = epub.EpubBook()
    book.set_identifier("alice-epub")
    book.set_title(TITLE)
    book.set_language("en")
    book.add_author("Lewis Carroll")
    chapter = epub.EpubHtml(title="Ch1", file_name="ch1.xhtml", lang="en")
    chapter.content = b"<html><body><p>Down the rabbit hole.</p></body></html>"
    book.add_item(chapter)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]
    epub.write_epub(str(dest), book)


def _catalog_titles() -> list[str]:
    result = CliRunner().invoke(cli, ["ls"], catch_exceptions=False)
    return [line for line in result.output.splitlines() if TITLE in line]


@pytest.mark.parametrize("suffix", [".azw3", ".azw"])
def test_ac1_convert_kindle_file_writes_epub(tmp_path: Path, suffix: str) -> None:
    """AC1: convert <file>.azw3 / .azw writes an EPUB and exits 0."""
    source = _copy(tmp_path / f"alice{suffix}")
    out = tmp_path / "out"

    result = CliRunner().invoke(cli, ["convert", str(source), "-o", str(out)])

    assert result.exit_code == 0, result.output
    assert list(out.rglob("*.epub")), result.output


def test_ac2_add_directory_converts_kindle_files(tmp_path: Path) -> None:
    """AC2: add <dir> --convert discovers .azw and .AZW3 recursively and reports Kindle counts."""
    _copy(tmp_path / "src" / "a" / "alice.azw")
    _copy(tmp_path / "src" / "b" / "alice.AZW3")

    result = CliRunner().invoke(
        cli,
        ["add", str(tmp_path / "src"), "--convert", "--no-match", "--force-duplicates"],
    )

    assert result.exit_code == 0, result.output
    assert "Converted 2 of 2 Kindle file(s)" in result.output
    assert len(_catalog_titles()) == 2


def test_ac3_add_directory_skips_kindle_file_next_to_epub(tmp_path: Path) -> None:
    """AC3: an AZW3 in a folder that already holds an EPUB is skipped, like MOBI today."""
    src = tmp_path / "src"
    _copy(src / "alice.azw3")
    _write_epub(src / "alice.epub")

    result = CliRunner().invoke(cli, ["add", str(src), "--convert", "--no-match"])

    assert "Skipped 1 Kindle file(s)" in result.output


def test_ac4_add_single_kindle_file(tmp_path: Path) -> None:
    """AC4: add <file>.azw3 converts and catalogs the book."""
    source = _copy(tmp_path / "alice.azw3")

    result = CliRunner().invoke(cli, ["add", str(source), "--no-match"])

    assert result.exit_code == 0, result.output
    assert len(_catalog_titles()) == 1
    assert source.exists()


def test_ac5_info_kindle_file_prints_metadata(tmp_path: Path) -> None:
    """AC5: info <file>.azw3 prints title and author read from the file."""
    source = _copy(tmp_path / "alice.azw3")

    result = CliRunner().invoke(cli, ["info", str(source)])

    assert result.exit_code == 0, result.output
    assert TITLE in result.output
    assert "Lewis Carroll" in result.output


def test_ac6_convert_drm_file_fails_clearly(tmp_path: Path) -> None:
    """AC6: a DRM-protected AZW3 exits non-zero with the DRM message."""
    source = _drm_copy(tmp_path / "locked.azw3")

    result = CliRunner().invoke(cli, ["convert", str(source), "-o", str(tmp_path / "out")])

    assert result.exit_code != 0
    assert f"locked.azw3 {DRM_MESSAGE}" in " ".join(result.output.split())


def test_ac7_batch_continues_past_drm_file(tmp_path: Path) -> None:
    """AC7: in a batch, the DRM file counts as an error and the others still convert."""
    src = tmp_path / "src"
    _drm_copy(src / "locked.azw3")
    _copy(src / "alice.azw3")
    out = tmp_path / "out"

    result = CliRunner().invoke(cli, ["convert", str(src), "-o", str(out)])

    assert result.exit_code != 0
    assert DRM_MESSAGE in " ".join(result.output.split())
    assert "1 converted" in result.output
    assert "1 error" in result.output
    assert len(list(out.rglob("*.epub"))) == 1


def test_ac8_unsupported_suffix_lists_kindle_formats(tmp_path: Path) -> None:
    """AC8: an unsupported suffix is rejected and the message lists .azw and .azw3."""
    source = tmp_path / "book.kfx"
    source.write_bytes(b"not a book")

    result = CliRunner().invoke(cli, ["add", str(source), "--no-match"])

    assert result.exit_code != 0
    assert re.search(r"\.azw\b", result.output)
    assert ".azw3" in result.output
