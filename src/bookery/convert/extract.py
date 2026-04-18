# ABOUTME: Extracts a PDF into a RawDoc with per-page blocks (text + bbox + font size).
# ABOUTME: Outline comes from pypdf; block geometry comes from pdfplumber character grouping.

from pathlib import Path
from statistics import median
from typing import Any

import pdfplumber
import pypdf
from pypdf.generic import Destination, IndirectObject, NumberObject

from bookery.convert.types import OutlineEntry, RawBlock, RawDoc, RawPage

# Two chars are "on the same line" if their y0 differs by less than this fraction
# of the char height. Tuned for typical trade-book leading.
LINE_Y_TOLERANCE = 0.5


def _group_chars_to_lines(
    chars: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Cluster chars into lines by y0 (top coordinate), preserving x order within each line."""
    if not chars:
        return []
    # Sort by top, then by x0, so same-row chars land adjacent.
    ordered = sorted(chars, key=lambda c: (round(float(c["top"]), 1), float(c["x0"])))
    lines: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_top: float | None = None
    for ch in ordered:
        top = float(ch["top"])
        size = float(ch.get("size", 10))
        tolerance = max(1.0, size * LINE_Y_TOLERANCE)
        if current_top is None or abs(top - current_top) <= tolerance:
            current.append(ch)
            if current_top is None:
                current_top = top
        else:
            lines.append(current)
            current = [ch]
            current_top = top
    if current:
        lines.append(current)
    return lines


def _line_to_block(line: list[dict[str, Any]], page_no: int) -> RawBlock | None:
    if not line:
        return None
    ordered = sorted(line, key=lambda c: float(c["x0"]))
    text = "".join(str(c.get("text", "")) for c in ordered).strip()
    if not text:
        return None
    x0 = min(float(c["x0"]) for c in ordered)
    x1 = max(float(c["x1"]) for c in ordered)
    top = min(float(c["top"]) for c in ordered)
    bottom = max(float(c["bottom"]) for c in ordered)
    sizes = [float(c.get("size", 10)) for c in ordered]
    font_size = float(median(sizes)) if sizes else 10.0
    return RawBlock(text=text, page=page_no, bbox=(x0, top, x1, bottom), font_size=font_size)


def _extract_outline(path: Path) -> tuple[OutlineEntry, ...]:
    try:
        reader = pypdf.PdfReader(str(path))
    except Exception:
        return ()
    entries: list[OutlineEntry] = []

    def walk(items: list[Any], level: int) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item, level + 1)
                continue
            if not isinstance(item, Destination):
                continue
            title_attr = getattr(item, "title", None)
            title = str(title_attr) if title_attr else ""
            page_num = _destination_page(reader, item)
            if title and page_num is not None:
                entries.append(OutlineEntry(title=title, page=page_num, level=level))

    try:
        outline = reader.outline
    except Exception:
        return ()
    if outline:
        walk(list(outline), level=1)
    return tuple(entries)


def _destination_page(reader: pypdf.PdfReader, dest: Destination) -> int | None:
    page_ref = dest.page
    if isinstance(page_ref, NumberObject):
        return int(page_ref) + 1  # pypdf page index is 0-based
    try:
        page_obj = (
            page_ref.get_object() if isinstance(page_ref, IndirectObject) else page_ref
        )
        if page_obj is None:
            return None
        idx = reader.get_page_number(page_obj)  # type: ignore[arg-type]
    except Exception:
        return None
    if idx is None:
        return None
    return int(idx) + 1


def extract(pdf_path: Path) -> RawDoc:
    """Extract a PDF into a RawDoc of per-page text blocks plus its outline."""
    pages: list[RawPage] = []
    with pdfplumber.open(pdf_path) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            chars = list(page.chars)
            lines = _group_chars_to_lines(chars)
            blocks: list[RawBlock] = []
            for line in lines:
                block = _line_to_block(line, idx)
                if block is not None:
                    blocks.append(block)
            pages.append(
                RawPage(
                    number=idx,
                    width=float(page.width),
                    height=float(page.height),
                    blocks=tuple(blocks),
                )
            )
    return RawDoc(pages=tuple(pages), outline=_extract_outline(pdf_path))
