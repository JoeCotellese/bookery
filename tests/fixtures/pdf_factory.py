# ABOUTME: Synthetic PDF factory for tests — builds text-based PDFs via reportlab.
# ABOUTME: Keeps fixtures hermetic and avoids committing binary test data.

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def write_text_pdf(
    path: Path,
    pages: list[list[str]],
    *,
    title: str | None = None,
    author: str | None = None,
) -> Path:
    """Render a multi-page text PDF. `pages` is a list of lines per page."""
    c = canvas.Canvas(str(path), pagesize=letter)
    if title:
        c.setTitle(title)
    if author:
        c.setAuthor(author)
    _, height = letter
    for lines in pages:
        y = height - 72
        for line in lines:
            c.drawString(72, y, line)
            y -= 14
        c.showPage()
    c.save()
    return path


def write_blank_pdf(path: Path, *, page_count: int = 1) -> Path:
    """Render a PDF with no text content — stand-in for a scanned/image-only PDF."""
    c = canvas.Canvas(str(path), pagesize=letter)
    for _ in range(page_count):
        c.showPage()
    c.save()
    return path
