# ABOUTME: Unit tests for CLI source-format dispatch (suffix + magic bytes).

from pathlib import Path

import pytest

from bookery.cli._dispatch import UnknownFormatError, detect_source_format, find_kindle_files


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


@pytest.mark.parametrize("name", ["book.azw", "book.azw3", "BOOK.AZW3"])
def test_kindle_suffixes_route_to_mobi(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.write_bytes(b"anything")
    assert detect_source_format(path) == "mobi"


def test_unknown_extension_message_lists_kindle_suffixes(tmp_path: Path) -> None:
    path = tmp_path / "book.kfx"
    path.write_text("hello")
    with pytest.raises(UnknownFormatError, match=r"\.azw, \.azw3"):
        detect_source_format(path)


def test_find_kindle_files_is_recursive_and_case_insensitive(tmp_path: Path) -> None:
    wanted = [tmp_path / "a" / "one.azw", tmp_path / "b" / "two.AZW3", tmp_path / "three.Mobi"]
    ignored = [tmp_path / "a" / "one.epub", tmp_path / "notes.txt"]
    for path in wanted + ignored:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    (tmp_path / "dir.azw3").mkdir()

    assert find_kindle_files(tmp_path) == sorted(wanted)
