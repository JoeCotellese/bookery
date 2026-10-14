# ABOUTME: Acceptance test for #320: metadata write verification tolerates read-side normalization.
# ABOUTME: Drives apply_metadata_safely and `bookery add` with whitespace and HTML metadata.

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from bookery.cli import cli
from bookery.core import pipeline
from bookery.core.pipeline import apply_metadata_safely
from bookery.formats.epub import read_epub_metadata
from bookery.metadata import BookMetadata
from bookery.metadata.candidate import MetadataCandidate

BREATH_DESCRIPTION = (
    "Modern research is showing us that making even slight adjustments to the way "
    "we inhale and exhale can:\n\n"
    "- jump-start athletic performance  - rejuvenate internal organs  - halt snoring"
)


def test_ac1_double_space_description_is_kept(sample_epub: Path, tmp_path: Path) -> None:
    """AC1: a description with a double space writes, verifies, and reads back collapsed."""
    metadata = BookMetadata(title="Breath", authors=["James Nestor"], description="a  - b")

    result = apply_metadata_safely(sample_epub, metadata, tmp_path / "out")

    assert result.success, result.error
    assert result.path is not None and result.path.exists()
    assert read_epub_metadata(result.path).description == "a - b"


def test_ac2_html_description_is_written_as_plain_text(sample_epub: Path, tmp_path: Path) -> None:
    """AC2: an HTML description writes as plain text and verifies."""
    metadata = BookMetadata(
        title="Breath", authors=["James Nestor"], description="<p>Fish &amp; chips</p>"
    )

    result = apply_metadata_safely(sample_epub, metadata, tmp_path / "out")

    assert result.success, result.error
    assert result.path is not None
    assert read_epub_metadata(result.path).description == "Fish & chips"


def test_ac3_padded_title_publisher_language_verify(sample_epub: Path, tmp_path: Path) -> None:
    """AC3: leading/trailing whitespace on title, publisher, language does not fail verify."""
    metadata = BookMetadata(
        title=" Breath ",
        authors=["James Nestor"],
        publisher="Riverhead ",
        language=" en",
    )

    result = apply_metadata_safely(sample_epub, metadata, tmp_path / "out")

    assert result.success, result.error
    assert result.path is not None
    read_back = read_epub_metadata(result.path)
    assert read_back.title == "Breath"
    assert read_back.publisher == "Riverhead"
    assert read_back.language == "en"


def test_ac4_real_description_mismatch_still_fails(sample_epub: Path, tmp_path: Path) -> None:
    """AC4: verification still rejects a non-whitespace description difference."""
    real_write = pipeline.write_epub_metadata

    def tampering_write(path: Path, metadata: BookMetadata) -> None:
        real_write(path, replace(metadata, description="Something else entirely."))

    metadata = BookMetadata(title="Breath", authors=["James Nestor"], description="a  - b")

    with patch("bookery.core.pipeline.write_epub_metadata", side_effect=tampering_write):
        result = apply_metadata_safely(sample_epub, metadata, tmp_path / "out")

    assert not result.success
    assert result.error is not None and "description" in result.error


def test_ac5_add_keeps_enriched_copy(sample_epub: Path, _isolate_library_root: Path) -> None:
    """AC5: `bookery add --yes` with the Breath description keeps the enriched EPUB."""
    candidate = MetadataCandidate(
        metadata=BookMetadata(
            title="Breath",
            authors=["James Nestor"],
            language="en",
            description=BREATH_DESCRIPTION,
        ),
        confidence=0.99,
        source="openlibrary",
        source_id="test-breath",
    )
    provider = MagicMock()
    provider.search_by_isbn.return_value = [candidate]
    provider.search_by_title_author.return_value = [candidate]

    with patch("bookery.cli._match_helpers.build_metadata_provider", return_value=provider):
        result = CliRunner().invoke(cli, ["add", str(sample_epub), "--yes", "--no-covers"])

    assert result.exit_code == 0, result.output
    assert "Write failed" not in result.output
    assert "Verification failed" not in result.output
    enriched = [
        p for p in _isolate_library_root.rglob("*.epub") if read_epub_metadata(p).title == "Breath"
    ]
    assert len(enriched) == 1
    assert "performance - rejuvenate" in (read_epub_metadata(enriched[0]).description or "")
