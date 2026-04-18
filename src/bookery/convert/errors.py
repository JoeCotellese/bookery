# ABOUTME: Typed exceptions for the PDF-to-EPUB conversion pipeline.
# ABOUTME: Each carries an exit_code class attribute the CLI maps to process exit status.

from pathlib import Path


class ConvertError(Exception):
    """Base class for PDF conversion errors."""

    exit_code: int = 1


class PdfEncrypted(ConvertError):
    exit_code = 1

    def __init__(self, path: Path) -> None:
        super().__init__(f"{path} is encrypted. Remove protection before converting.")
        self.path = path


class PdfScanned(ConvertError):
    exit_code = 1

    def __init__(self, path: Path) -> None:
        super().__init__(
            f"{path} appears to be a scanned PDF. OCR is not yet supported."
        )
        self.path = path


class KepubifyMissing(ConvertError):
    exit_code = 3

    def __init__(self) -> None:
        super().__init__(
            "kepubify not found. Install with: brew install pgaskin/kepubify/kepubify"
        )


class LLMUnreachable(ConvertError):
    exit_code = 3

    def __init__(self, base_url: str) -> None:
        super().__init__(f"Cannot reach LLM at {base_url}. Is LM Studio running?")
        self.base_url = base_url


class LLMBadResponse(ConvertError):
    exit_code = 1

    def __init__(self, detail: str) -> None:
        super().__init__(f"LLM returned a malformed response: {detail}")
        self.detail = detail


class KepubifyFailed(ConvertError):
    exit_code = 1

    def __init__(self, detail: str) -> None:
        super().__init__(f"kepubify failed: {detail}")
        self.detail = detail
