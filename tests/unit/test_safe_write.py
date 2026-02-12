# ABOUTME: Unit tests for the non-destructive write pipeline.
# ABOUTME: Validates copy-then-modify behavior, name collisions, and original preservation.

from pathlib import Path

from bookery.core.pipeline import apply_metadata_safely
from bookery.formats.epub import read_epub_metadata
from bookery.metadata import BookMetadata


class TestApplyMetadataSafely:
    """Tests for apply_metadata_safely function."""

    def test_creates_copy_in_output_dir(self, sample_epub: Path, tmp_path: Path) -> None:
        """Modified copy is created in the output directory."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        metadata = BookMetadata(title="Updated Title", authors=["New Author"])

        result = apply_metadata_safely(sample_epub, metadata, output_dir)

        assert result.parent == output_dir
        assert result.exists()
        assert result.suffix == ".epub"

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

        read_back = read_epub_metadata(result)
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

        assert result.exists()
        assert result.name != sample_epub.name
        assert "_1" in result.stem

    def test_multiple_collisions_increment(self, sample_epub: Path, tmp_path: Path) -> None:
        """Multiple collisions increment the suffix counter."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        metadata = BookMetadata(title="Test")

        stem = sample_epub.stem
        (output_dir / sample_epub.name).write_text("collision 0")
        (output_dir / f"{stem}_1.epub").write_text("collision 1")

        result = apply_metadata_safely(sample_epub, metadata, output_dir)

        assert "_2" in result.stem

    def test_creates_output_dir_if_missing(self, sample_epub: Path, tmp_path: Path) -> None:
        """Output directory is created if it doesn't exist."""
        output_dir = tmp_path / "new_output"
        metadata = BookMetadata(title="Test")

        result = apply_metadata_safely(sample_epub, metadata, output_dir)

        assert output_dir.is_dir()
        assert result.exists()

    def test_preserves_epub_extension(self, sample_epub: Path, tmp_path: Path) -> None:
        """Output file always has .epub extension."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        metadata = BookMetadata(title="Test")

        result = apply_metadata_safely(sample_epub, metadata, output_dir)

        assert result.suffix == ".epub"
