# ABOUTME: MOBI extraction wrapper using the mobi (KindleUnpack) library.
# ABOUTME: Extracts MOBI files to EPUB or HTML and can assemble HTML into EPUB via ebooklib.

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from ebooklib import epub
from mobi import extract as mobi_extract

from bookery.metadata.types import BookMetadata

logger = logging.getLogger(__name__)


class MobiReadError(Exception):
    """Raised when a MOBI file cannot be read or extracted."""


@dataclass
class MobiExtractResult:
    """Result of extracting a MOBI file via KindleUnpack.

    Either epub_path or html_path will be set depending on the source format.
    The caller is responsible for cleaning up tempdir when done.
    """

    tempdir: Path
    format: str  # "epub" or "html"
    epub_path: Path | None = None
    html_path: Path | None = None


def extract_mobi(path: Path) -> MobiExtractResult:
    """Extract a MOBI file using the mobi library.

    Args:
        path: Path to the MOBI file.

    Returns:
        MobiExtractResult with the extracted file path and format.

    Raises:
        MobiReadError: If the file cannot be found or extracted.
    """
    if not path.exists():
        raise MobiReadError(f"File not found: {path}")

    try:
        tempdir_str, filepath_str = mobi_extract(str(path))
    except Exception as exc:
        raise MobiReadError(f"Failed to extract MOBI: {path}: {exc}") from exc

    tempdir = Path(tempdir_str)
    filepath = Path(filepath_str)

    if filepath.suffix.lower() == ".epub":
        return MobiExtractResult(
            tempdir=tempdir,
            format="epub",
            epub_path=filepath,
        )

    # Anything else (HTML, etc.) is treated as HTML output
    return MobiExtractResult(
        tempdir=tempdir,
        format="html",
        html_path=filepath,
    )


def assemble_epub_from_html(
    html_path: Path,
    output_path: Path,
    metadata: BookMetadata | None = None,
) -> Path:
    """Wrap an extracted HTML file into a valid EPUB using ebooklib.

    Args:
        html_path: Path to the HTML file from MOBI extraction.
        output_path: Where to write the assembled EPUB.
        metadata: Optional metadata to embed in the EPUB.

    Returns:
        The output_path where the EPUB was written.
    """
    html_content = html_path.read_bytes()

    book = epub.EpubBook()
    book.set_identifier(str(uuid.uuid4()))

    title = metadata.title if metadata else html_path.stem
    book.set_title(title)

    language = metadata.language if metadata else "en"
    book.set_language(language)

    if metadata and metadata.authors:
        for author in metadata.authors:
            book.add_author(author)

    chapter = epub.EpubHtml(title=title, file_name="content.xhtml", lang=language)
    chapter.content = html_content
    book.add_item(chapter)

    book.toc = [epub.Link("content.xhtml", title, "content")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]

    epub.write_epub(str(output_path), book)
    return output_path
