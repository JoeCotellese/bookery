# ABOUTME: Clean stage — strip running headers/footers, drop page numbers, stitch paragraphs.
# ABOUTME: Consumes a RawDoc (line-level blocks) and emits paragraph-level CleanDoc.

import re
from collections import Counter
from collections.abc import Iterable

from bookery.convert.types import CleanBlock, CleanDoc, RawBlock, RawDoc, RawPage

# A block is considered "in the top margin" if its top y is within this fraction
# of the page's top, and analogously for the bottom margin.
MARGIN_BAND_FRACTION = 0.15

# Consecutive lines merge into one paragraph if the vertical gap between them
# is no more than this multiple of their font size.
PARAGRAPH_GAP_MULTIPLE = 1.5

# Page-number patterns — standalone digits, roman numerals, "Page N", "- N -".
PAGE_NUMBER_RE = re.compile(
    r"^\s*(?:page\s+)?[\s\-\u2013\u2014]*(?:\d{1,4}|[ivxlcdm]{1,6})[\s\-\u2013\u2014]*$",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    """Collapse whitespace and lowercase for running-header frequency matching."""
    return re.sub(r"\s+", " ", text).strip().lower()


def _in_margin(block: RawBlock, page: RawPage) -> bool:
    band = page.height * MARGIN_BAND_FRACTION
    _, top, _, bottom = block.bbox
    return top <= band or bottom >= (page.height - band)


def _running_texts(doc: RawDoc, threshold: float) -> set[str]:
    """Normalized text strings that appear in the margin band on ≥ threshold * pages."""
    if not doc.pages:
        return set()
    counts: Counter[str] = Counter()
    for page in doc.pages:
        seen_on_page: set[str] = set()
        for block in page.blocks:
            if not _in_margin(block, page):
                continue
            key = _normalize(block.text)
            if not key or key in seen_on_page:
                continue
            seen_on_page.add(key)
            counts[key] += 1
    min_pages = max(2, round(threshold * len(doc.pages)))
    return {text for text, n in counts.items() if n >= min_pages}


def _is_page_number(block: RawBlock) -> bool:
    return bool(PAGE_NUMBER_RE.match(block.text.strip()))


def _should_drop(block: RawBlock, page: RawPage, running: set[str]) -> bool:
    if not _in_margin(block, page):
        return False
    if _is_page_number(block):
        return True
    return _normalize(block.text) in running


def _dehyphenate_join(left: str, right: str) -> str:
    """Join two lines, undoing a line-end hyphen when it's mid-word."""
    if left.endswith("-") and right and right[0].islower():
        return left[:-1] + right
    if not left:
        return right
    if not right:
        return left
    return f"{left} {right}"


def _same_paragraph(prev: RawBlock, curr: RawBlock) -> bool:
    if prev.page != curr.page:
        return False
    if abs(prev.font_size - curr.font_size) > 0.5:
        return False
    _, _, _, prev_bottom = prev.bbox
    _, curr_top, _, _ = curr.bbox
    gap = curr_top - prev_bottom
    return gap <= prev.font_size * PARAGRAPH_GAP_MULTIPLE


def _merge_paragraphs(blocks: Iterable[RawBlock]) -> list[CleanBlock]:
    merged: list[CleanBlock] = []
    buffer: list[RawBlock] = []

    def flush() -> None:
        if not buffer:
            return
        text = buffer[0].text
        for b in buffer[1:]:
            text = _dehyphenate_join(text, b.text)
        merged.append(
            CleanBlock(
                text=text,
                page=buffer[0].page,
                font_size=buffer[0].font_size,
            )
        )

    for block in blocks:
        if buffer and _same_paragraph(buffer[-1], block):
            buffer.append(block)
        else:
            flush()
            buffer = [block]
    flush()
    return merged


def clean(doc: RawDoc, *, header_footer_threshold: float = 0.6) -> CleanDoc:
    """Strip running headers/footers and page numbers; stitch lines into paragraphs."""
    running = _running_texts(doc, header_footer_threshold)
    filtered: list[RawBlock] = []
    for page in doc.pages:
        for block in page.blocks:
            if _should_drop(block, page, running):
                continue
            filtered.append(block)
    paragraphs = _merge_paragraphs(filtered)
    return CleanDoc(blocks=tuple(paragraphs), outline=doc.outline)
