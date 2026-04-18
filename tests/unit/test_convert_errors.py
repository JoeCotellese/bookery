# ABOUTME: Unit tests for convert.errors exit code class attributes and messages.

from pathlib import Path

from bookery.convert.errors import (
    KepubifyFailed,
    KepubifyMissing,
    LLMBadResponse,
    LLMUnreachable,
    PdfEncrypted,
    PdfScanned,
)


def test_exit_codes() -> None:
    assert PdfEncrypted.exit_code == 1
    assert PdfScanned.exit_code == 1
    assert KepubifyMissing.exit_code == 3
    assert LLMUnreachable.exit_code == 3
    assert LLMBadResponse.exit_code == 1
    assert KepubifyFailed.exit_code == 1


def test_pdf_encrypted_message() -> None:
    err = PdfEncrypted(Path("/tmp/book.pdf"))
    assert "encrypted" in str(err)
    assert "/tmp/book.pdf" in str(err)


def test_pdf_scanned_message() -> None:
    err = PdfScanned(Path("/tmp/scan.pdf"))
    assert "scanned" in str(err)
    assert "OCR" in str(err)


def test_kepubify_missing_message() -> None:
    err = KepubifyMissing()
    assert "kepubify not found" in str(err)
    assert "brew install" in str(err)


def test_llm_unreachable_message() -> None:
    err = LLMUnreachable("http://localhost:1234/v1")
    assert "http://localhost:1234/v1" in str(err)
    assert "LM Studio" in str(err)
