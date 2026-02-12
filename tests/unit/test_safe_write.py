# ABOUTME: Unit tests for the non-destructive write pipeline.
# ABOUTME: Validates copy-then-modify behavior, name collisions, verification, and cleanup.

from pathlib import Path
from unittest.mock import patch

from bookery.core.pipeline import apply_metadata_safely
from bookery.formats.epub import EpubReadError, read_epub_metadata
from bookery.metadata import BookMetadata


class TestApplyMetadataSafely:
    """Tests for apply_metadata_safely function."""

    def test_creates_copy_in_output_dir(self, sample_epub: Path, tmp_path: Path) -> None:
        """Modified copy is created in the output directory."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        metadata = BookMetadata(title="Updated Title", authors=["New Author"])

        result = apply_metadata_safely(sample_epub, metadata, output_dir)

        assert result.path is not None
        assert result.path.parent == output_dir
        assert result.path.exists()
        assert result.path.suffix == ".epub"

    def test_original_file_unchanged(self, sample_epub: Path, tmp_path: Path) -> None:
        """Original EPUB file is byte-identical after pipeline runs."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        original_bytes = sample_epub.read_bytes()

        metadata = BookMetadata(title="Changed Title", authors=["Changed Author"])
        apply_metadata_safely(sample_epub, metadata, output_dir)

        assert sample_epub.read_bytes() == original_bytes

    def test_copy_has_updated_metadata(self, sample_epub: Path, tmp_path: Path) -> None:
        """The copy has the new metadata written to it."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        metadata = BookMetadata(
            title="Il Nome della Rosa",
            authors=["Umberto Eco"],
            language="it",
        )

        result = apply_metadata_safely(sample_epub, metadata, output_dir)

        assert result.path is not None
        read_back = read_epub_metadata(result.path)
        assert read_back.title == "Il Nome della Rosa"
        assert read_back.authors == ["Umberto Eco"]

    def test_name_collision_adds_suffix(self, sample_epub: Path, tmp_path: Path) -> None:
        """When output file already exists, a numeric suffix is added."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        metadata = BookMetadata(title="Test")

        # Create a file that would collide
        (output_dir / sample_epub.name).write_text("occupying the name")

        result = apply_metadata_safely(sample_epub, metadata, output_dir)

        assert result.path is not None
        assert result.path.exists()
        assert result.path.name != sample_epub.name
        assert "_1" in result.path.stem

    def test_multiple_collisions_increment(self, sample_epub: Path, tmp_path: Path) -> None:
        """Multiple collisions increment the suffix counter."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        metadata = BookMetadata(title="Test")

        stem = sample_epub.stem
        (output_dir / sample_epub.name).write_text("collision 0")
        (output_dir / f"{stem}_1.epub").write_text("collision 1")

        result = apply_metadata_safely(sample_epub, metadata, output_dir)

        assert result.path is not None
        assert "_2" in result.path.stem

    def test_creates_output_dir_if_missing(self, sample_epub: Path, tmp_path: Path) -> None:
        """Output directory is created if it doesn't exist."""
        output_dir = tmp_path / "new_output"
        metadata = BookMetadata(title="Test")

        result = apply_metadata_safely(sample_epub, metadata, output_dir)

        assert output_dir.is_dir()
        assert result.path is not None
        assert result.path.exists()

    def test_preserves_epub_extension(self, sample_epub: Path, tmp_path: Path) -> None:
        """Output file always has .epub extension."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        metadata = BookMetadata(title="Test")

        result = apply_metadata_safely(sample_epub, metadata, output_dir)

        assert result.path is not None
        assert result.path.suffix == ".epub"


class TestWriteBackVerification:
    """Tests for write-back verification in apply_metadata_safely."""

    def test_result_contains_verified_fields(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        """WriteResult has verification entries for written fields."""
        output_dir = tmp_path / "output"
        metadata = BookMetadata(
            title="Test Title",
            authors=["Test Author"],
            language="en",
        )

        result = apply_metadata_safely(sample_epub, metadata, output_dir)

        assert result.success is True
        assert len(result.verified_fields) > 0
        field_names = [v.field for v in result.verified_fields]
        assert "title" in field_names
        assert "authors" in field_names
        assert "language" in field_names

    def test_result_includes_field_details(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        """FieldVerification includes expected and actual values."""
        output_dir = tmp_path / "output"
        metadata = BookMetadata(title="Verified Title", authors=["Verified Author"])

        result = apply_metadata_safely(sample_epub, metadata, output_dir)

        title_field = next(v for v in result.verified_fields if v.field == "title")
        assert title_field.expected == "Verified Title"
        assert title_field.actual == "Verified Title"
        assert title_field.passed is True

    def test_write_failure_cleans_up_copy(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        """If write_epub_metadata raises, the copy is deleted."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        metadata = BookMetadata(title="Test")

        with patch(
            "bookery.core.pipeline.write_epub_metadata",
            side_effect=EpubReadError("write failed"),
        ):
            result = apply_metadata_safely(sample_epub, metadata, output_dir)

        assert result.success is False
        assert result.error is not None
        # The failed copy should be cleaned up
        assert not list(output_dir.glob("*.epub"))

    def test_verification_failure_cleans_up_copy(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        """If read-back returns wrong title, the copy is deleted."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        metadata = BookMetadata(title="Expected Title", authors=["Author"])

        wrong_metadata = BookMetadata(title="Wrong Title", authors=["Author"])
        with patch(
            "bookery.core.pipeline.read_epub_metadata", return_value=wrong_metadata
        ):
            result = apply_metadata_safely(sample_epub, metadata, output_dir)

        assert result.success is False
        assert not list(output_dir.glob("*.epub"))

    def test_verification_readback_failure_cleans_up(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        """If read-back raises, the copy is deleted."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        metadata = BookMetadata(title="Test")

        with patch(
            "bookery.core.pipeline.read_epub_metadata",
            side_effect=EpubReadError("read failed"),
        ):
            result = apply_metadata_safely(sample_epub, metadata, output_dir)

        assert result.success is False
        assert result.error is not None
        assert not list(output_dir.glob("*.epub"))

    def test_only_written_fields_are_verified(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        """None fields are excluded from verification."""
        output_dir = tmp_path / "output"
        metadata = BookMetadata(
            title="Test Title",
            authors=[],
            language=None,
            publisher=None,
            description=None,
        )

        result = apply_metadata_safely(sample_epub, metadata, output_dir)

        field_names = [v.field for v in result.verified_fields]
        assert "title" in field_names
        # None fields should not be verified
        assert "language" not in field_names
        assert "publisher" not in field_names
        assert "description" not in field_names

    def test_author_order_independence(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        """Authors verified with sorted comparison — order doesn't matter."""
        output_dir = tmp_path / "output"
        metadata = BookMetadata(
            title="Test",
            authors=["Bravo Author", "Alpha Author"],
        )

        result = apply_metadata_safely(sample_epub, metadata, output_dir)

        authors_field = next(v for v in result.verified_fields if v.field == "authors")
        assert authors_field.passed is True

    def test_language_case_insensitive(
        self, sample_epub: Path, tmp_path: Path
    ) -> None:
        """Language verification is case-insensitive ('EN' matches 'en')."""
        output_dir = tmp_path / "output"
        metadata = BookMetadata(title="Test", authors=["Author"], language="EN")

        result = apply_metadata_safely(sample_epub, metadata, output_dir)

        lang_field = next(v for v in result.verified_fields if v.field == "language")
        assert lang_field.passed is True
