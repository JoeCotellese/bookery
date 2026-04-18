# ABOUTME: Unit tests for CLI source-format dispatch (suffix + magic bytes).

from pathlib import Path

import pytest

from bookery.cli._dispatch import UnknownFormatError, detect_source_format


def test_epub_by_suffix(tmp_path: Path) -> None:
    path = tmp_path / "book.epub"
    path.write_bytes(b"PK\x03\x04 anything")
    assert detect_source_format(path) == "epub"


def test_mobi_by_suffix(tmp_path: Path) -> None:
    path = tmp_path / "book.mobi"
    path.write_bytes(b"anything")
    assert detect_source_format(path) == "mobi"


def test_pdf_valid_magic(tmp_path: Path) -> None:
    path = tmp_path / "book.pdf"
    path.write_bytes(b"%PDF-1.7\n...")
    assert detect_source_format(path) == "pdf"


def test_pdf_suffix_but_not_pdf(tmp_path: Path) -> None:
    path = tmp_path / "fake.pdf"
    path.write_bytes(b"this is not a pdf")
    with pytest.raises(UnknownFormatError):
        detect_source_format(path)


def test_unknown_extension(tmp_path: Path) -> None:
    path = tmp_path / "book.txt"
    path.write_text("hello")
    with pytest.raises(UnknownFormatError):
        detect_source_format(path)
