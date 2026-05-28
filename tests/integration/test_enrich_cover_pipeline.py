# ABOUTME: Integration test for the enrich cover-apply path (issue #200).
# ABOUTME: A candidate's fetched cover bytes end up embedded in the rewritten EPUB copy.

from pathlib import Path

from bookery.core.pipeline import apply_metadata_safely
from bookery.formats.epub import extract_cover_bytes, read_epub_metadata
from bookery.metadata.types import BookMetadata

_FETCHED_JPEG = b"\xff\xd8\xff\xe0" + b"fetched-cover" * 16


class TestApplyEmbedsCover:
    """apply_metadata_safely writes the supplied cover into the non-destructive copy."""

    def test_cover_bytes_land_in_rewritten_epub(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        original_bytes = sample_epub.read_bytes()
        # The starting EPUB has no cover.
        assert read_epub_metadata(sample_epub).cover_image is None

        proposed = BookMetadata(title="Dune", authors=["Frank Herbert"])
        output_dir = tmp_path / "output"

        result = apply_metadata_safely(
            sample_epub, proposed, output_dir, cover_image=_FETCHED_JPEG
        )

        assert result.success is True
        assert result.path is not None

        # The rewritten copy carries the cover bytes and re-reads cleanly.
        re_read = read_epub_metadata(result.path)
        assert re_read.title == "Dune"
        assert re_read.cover_image == _FETCHED_JPEG

        # The web cover route extracts via extract_cover_bytes — confirm it
        # surfaces exactly the fetched bytes.
        extracted = extract_cover_bytes(result.path)
        assert extracted is not None
        data, content_type = extracted
        assert data == _FETCHED_JPEG
        assert content_type == "image/jpeg"

        # Non-destructive guarantee: the original source EPUB is untouched.
        assert sample_epub.read_bytes() == original_bytes

    def test_no_cover_bytes_leaves_copy_coverless(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        proposed = BookMetadata(title="Dune", authors=["Frank Herbert"])
        output_dir = tmp_path / "output"

        result = apply_metadata_safely(sample_epub, proposed, output_dir)

        assert result.success is True
        assert result.path is not None
        assert read_epub_metadata(result.path).cover_image is None
