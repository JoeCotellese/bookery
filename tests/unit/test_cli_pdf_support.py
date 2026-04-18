# ABOUTME: Unit tests for _pdf_support.convert_pdf_to_epub wrapper.

from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from bookery.cli._pdf_support import convert_pdf_to_epub
from bookery.core.pdf_converter import PdfConvertResult


def test_convert_pdf_to_epub_returns_epub_path(tmp_path: Path) -> None:
    src = tmp_path / "src.pdf"
    epub = tmp_path / "src.epub"
    result = PdfConvertResult(source=src, epub_path=epub, warnings=())

    console = Console(file=Path.open(tmp_path / "log.txt", "w"), force_terminal=False)
    with patch(
        "bookery.cli._pdf_support.convert_pdf", return_value=result
    ) as mocked:
        returned = convert_pdf_to_epub(src, tmp_path, console=console)
    console.file.close()

    assert returned == epub
    mocked.assert_called_once()


def test_convert_pdf_to_epub_prints_warnings(tmp_path: Path) -> None:
    src = tmp_path / "src.pdf"
    epub = tmp_path / "src.epub"
    result = PdfConvertResult(
        source=src, epub_path=epub, warnings=("something fishy",)
    )
    log = tmp_path / "log.txt"
    console = Console(file=Path.open(log, "w"), force_terminal=False)
    with patch("bookery.cli._pdf_support.convert_pdf", return_value=result):
        convert_pdf_to_epub(src, tmp_path, console=console)
    console.file.close()

    text = log.read_text()
    assert "something fishy" in text
