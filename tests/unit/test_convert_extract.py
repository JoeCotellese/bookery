# ABOUTME: Unit tests for convert.extract — PDF → RawDoc with synthetic reportlab fixtures.

from pathlib import Path

from bookery.convert.extract import extract
from tests.fixtures.pdf_factory import write_text_pdf


def test_extract_single_page(tmp_path: Path) -> None:
    pdf = write_text_pdf(
        tmp_path / "one.pdf",
        [["Hello world.", "Second line here."]],
    )
    doc = extract(pdf)
    assert len(doc.pages) == 1
    page = doc.pages[0]
    assert page.number == 1
    texts = [b.text for b in page.blocks]
    assert any("Hello world" in t for t in texts)
    assert any("Second line" in t for t in texts)


def test_extract_multi_page(tmp_path: Path) -> None:
    pdf = write_text_pdf(
        tmp_path / "multi.pdf",
        [
            ["Page one body."],
            ["Page two body."],
            ["Page three body."],
        ],
    )
    doc = extract(pdf)
    assert len(doc.pages) == 3
    assert doc.pages[0].number == 1
    assert doc.pages[2].number == 3


def test_extract_bbox_and_font_size(tmp_path: Path) -> None:
    pdf = write_text_pdf(tmp_path / "sizes.pdf", [["Sample line text."]])
    doc = extract(pdf)
    block = doc.pages[0].blocks[0]
    x0, top, x1, bottom = block.bbox
    assert x1 > x0
    assert bottom > top
    assert block.font_size > 0


def test_extract_no_outline_when_absent(tmp_path: Path) -> None:
    pdf = write_text_pdf(tmp_path / "no_outline.pdf", [["Just text."]])
    doc = extract(pdf)
    assert doc.outline == ()
