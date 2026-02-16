# ABOUTME: MOBI-to-EPUB conversion orchestration.
# ABOUTME: Extracts MOBI files and produces EPUB output, handling both KF8 and legacy formats.

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from bookery.formats.epub import EpubReadError, read_epub_metadata
from bookery.formats.mobi import (
    MobiReadError,
    assemble_epub_from_html,
    extract_mobi,
    parse_ncx_toc,
    parse_opf_metadata,
    split_html_by_anchors,
)
from bookery.metadata.types import BookMetadata

logger = logging.getLogger(__name__)


@dataclass
class ConvertResult:
    """Result of converting a single MOBI file to EPUB."""

    source: Path
    epub_path: Path | None
    success: bool
    skipped: bool = False
    metadata: BookMetadata | None = None
    error: str | None = None


def convert_one(
    mobi_path: Path,
    output_dir: Path,
    force: bool = False,
) -> ConvertResult:
    """Convert a single MOBI file to EPUB.

    Pipeline: extract → copy/assemble → read metadata → cleanup tempdir.

    Args:
        mobi_path: Path to the source MOBI file.
        output_dir: Directory for the output EPUB.
        force: If True, overwrite existing output files.

    Returns:
        ConvertResult with the conversion outcome.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    epub_name = mobi_path.stem + ".epub"
    output_path = output_dir / epub_name

    # Skip if output already exists and force is off
    if output_path.exists() and not force:
        return ConvertResult(
            source=mobi_path,
            epub_path=output_path,
            success=True,
            skipped=True,
        )

    # Extract MOBI
    try:
        extract_result = extract_mobi(mobi_path)
    except MobiReadError as exc:
        return ConvertResult(
            source=mobi_path,
            epub_path=None,
            success=False,
            error=str(exc),
        )

    try:
        if extract_result.format == "epub":
            shutil.copy2(extract_result.epub_path, output_path)
        else:
            opf_metadata = parse_opf_metadata(extract_result.opf_path)

            # Parse NCX TOC and split HTML into chapters if available
            chapters = None
            nav_points = parse_ncx_toc(extract_result.ncx_path)
            if nav_points:
                html_content = extract_result.html_path.read_text(
                    encoding="utf-8", errors="replace",
                )
                chapters = split_html_by_anchors(html_content, nav_points)
                if chapters:
                    logger.info(
                        "Split %s into %d chapters from NCX",
                        extract_result.html_path.name,
                        len(chapters),
                    )
                else:
                    logger.warning(
                        "NCX had %d nav points but no anchors found in HTML",
                        len(nav_points),
                    )

            assemble_epub_from_html(
                extract_result.html_path,
                output_path,
                metadata=opf_metadata,
                images_dir=extract_result.images_dir,
                chapters=chapters if chapters else None,
            )

        # Read metadata from the resulting EPUB
        metadata = None
        try:
            metadata = read_epub_metadata(output_path)
        except EpubReadError as exc:
            logger.warning("Could not read metadata from converted EPUB: %s", exc)

        return ConvertResult(
            source=mobi_path,
            epub_path=output_path,
            success=True,
            metadata=metadata,
        )
    except Exception as exc:
        return ConvertResult(
            source=mobi_path,
            epub_path=None,
            success=False,
            error=str(exc),
        )
    finally:
        # Always clean up the extraction tempdir
        if extract_result.tempdir.exists():
            shutil.rmtree(extract_result.tempdir)
