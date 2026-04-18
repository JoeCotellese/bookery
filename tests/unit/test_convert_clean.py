# ABOUTME: Unit tests for convert.clean — running headers, page numbers, dehyphenation, stitching.

from bookery.convert.clean import clean
from bookery.convert.types import RawBlock, RawDoc, RawPage


def _page(number: int, blocks: list[RawBlock], height: float = 800.0) -> RawPage:
    return RawPage(number=number, width=612.0, height=height, blocks=tuple(blocks))


def _block(
    text: str,
    top: float,
    bottom: float,
    font_size: float = 11.0,
    page: int = 1,
) -> RawBlock:
    return RawBlock(
        text=text, page=page, bbox=(72.0, top, 540.0, bottom), font_size=font_size
    )


def test_strips_running_header_across_pages() -> None:
    # "My Book Title" at top of every page → should be stripped.
    pages = [
        _page(
            n,
            [
                _block("My Book Title", top=10, bottom=22, page=n),
                _block(f"Body text on page {n}.", top=100, bottom=114, page=n),
            ],
        )
        for n in range(1, 6)
    ]
    doc = RawDoc(pages=tuple(pages), outline=())
    result = clean(doc)
    texts = [b.text for b in result.blocks]
    assert not any("My Book Title" in t for t in texts)
    assert all(f"Body text on page {n}" in " ".join(texts) for n in range(1, 6))


def test_drops_page_numbers_in_margin() -> None:
    pages = [
        _page(
            n,
            [
                _block("Chapter body content.", top=200, bottom=214, page=n),
                _block(str(n), top=770, bottom=785, page=n),  # bottom margin
            ],
        )
        for n in range(1, 4)
    ]
    doc = RawDoc(pages=tuple(pages), outline=())
    result = clean(doc)
    texts = [b.text for b in result.blocks]
    for n in range(1, 4):
        assert str(n) not in texts


def test_dehyphenates_across_line_break() -> None:
    pages = [
        _page(
            1,
            [
                _block("This is an exam-", top=300, bottom=314, page=1),
                _block("ple sentence.", top=315, bottom=329, page=1),
            ],
        )
    ]
    doc = RawDoc(pages=tuple(pages), outline=())
    result = clean(doc)
    assert result.blocks[0].text == "This is an example sentence."


def test_stitches_paragraph_across_page_break_is_not_merged_by_default() -> None:
    # Different pages -> different paragraphs (conservative default).
    pages = [
        _page(
            1,
            [_block("First sentence on page one.", top=700, bottom=714, page=1)],
        ),
        _page(
            2,
            [_block("Continuation on page two.", top=100, bottom=114, page=2)],
        ),
    ]
    doc = RawDoc(pages=tuple(pages), outline=())
    result = clean(doc)
    assert len(result.blocks) == 2


def test_preserves_outline_passthrough() -> None:
    from bookery.convert.types import OutlineEntry

    outline = (OutlineEntry(title="Ch 1", page=1, level=1),)
    doc = RawDoc(pages=(_page(1, [_block("Body.", 100, 114)]),), outline=outline)
    result = clean(doc)
    assert result.outline == outline


def test_font_size_boundary_starts_new_paragraph() -> None:
    pages = [
        _page(
            1,
            [
                _block("Chapter One", top=100, bottom=128, font_size=18.0, page=1),
                _block("Normal paragraph body.", top=150, bottom=164, font_size=11.0, page=1),
            ],
        )
    ]
    doc = RawDoc(pages=tuple(pages), outline=())
    result = clean(doc)
    assert len(result.blocks) == 2
    assert result.blocks[0].font_size == 18.0
    assert result.blocks[1].font_size == 11.0
