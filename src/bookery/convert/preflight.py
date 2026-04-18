# ABOUTME: Pre-conversion gates — LLM reachability and PDF sanity.
# ABOUTME: Runs before any extraction work so users fail fast with actionable messages.

from pathlib import Path

import httpx
import pdfplumber
import pypdf

from bookery.convert.errors import (
    LLMUnreachable,
    PdfEncrypted,
    PdfScanned,
)

SCANNED_CHAR_THRESHOLD = 50  # chars/page average, below which we assume image-only
SCANNED_SAMPLE_PAGES = 5


def check_llm(base_url: str, *, timeout: float = 2.0) -> None:
    """Raise LLMUnreachable if the LM Studio OpenAI-compatible endpoint is down."""
    models_url = base_url.rstrip("/") + "/models"
    try:
        response = httpx.get(models_url, timeout=timeout)
    except httpx.HTTPError as exc:
        raise LLMUnreachable(base_url) from exc
    if response.status_code >= 500:
        raise LLMUnreachable(base_url)


def check_pdf(path: Path) -> None:
    """Raise PdfEncrypted for protected PDFs, PdfScanned for image-only PDFs."""
    reader = pypdf.PdfReader(str(path))
    if reader.is_encrypted:
        raise PdfEncrypted(path)

    with pdfplumber.open(path) as pdf:
        total_pages = len(pdf.pages)
        if total_pages == 0:
            raise PdfScanned(path)
        sample_count = min(SCANNED_SAMPLE_PAGES, total_pages)
        # Spread the sample across the document to catch mixed-content PDFs.
        step = max(1, total_pages // sample_count)
        indices = list(range(0, total_pages, step))[:sample_count]
        total_chars = 0
        for i in indices:
            text = pdf.pages[i].extract_text() or ""
            total_chars += len(text)
        avg = total_chars / len(indices)
        if avg < SCANNED_CHAR_THRESHOLD:
            raise PdfScanned(path)
